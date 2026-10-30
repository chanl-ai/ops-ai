"""A paused step's calls in words a reviewer reads (c-289): the question the step asks, what each option does, and
the values each call would send, without tool names, raw keys or raw floats. A tool's reviewer card template
(catalog `approval`) words it when there is one; any other operation is worded from its input schema's titles. The
same functions word every workflow's review, so nothing here knows one use case."""

from __future__ import annotations

import re
from collections.abc import Mapping
from contextvars import ContextVar
from typing import Any, cast

from ops_identity import ServiceCallError, ServiceUnreachable
from ops_service_kit.errors import ApiError

from .deps import Runtime

# What the dev seed and tools-service's seed record as who asked for a review; a person reads it as Setup.
SEEDED_REQUESTERS = frozenset({"seed", "the tools-service seed"})


def requester(raw: str) -> str:
    """Who asked for a review as a person reads it: a seeded request is Setup, anyone else as recorded."""
    return "Setup" if raw in SEEDED_REQUESTERS else raw


_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_]+)\}")
_FILE_ID = re.compile(r"^fil_[A-Za-z0-9]+$")
# A value only a machine reads (mod_core_banking, apr_f150a1a6, wfrun_…): an id, nothing a person decides on.
_MACHINE_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


def _norm(key: str) -> str:
    """accountId, account_id and AccountID name one input, as templates and calls spell it differently."""
    return key.replace("_", "").lower()


def humanize(key: str) -> str:
    """place_hold to "Place hold", accountId to "Account id"."""
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key).replace("_", " ").replace("-", " ").split()
    return " ".join(words).capitalize()


def shown(value: Any, *, money: bool, currency: str | None) -> str:
    """A value as a person reads it: money to two decimals with its currency, other numbers grouped and without a
    trailing .0, yes or no for booleans, lists joined."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        if money:
            return f"{value:,.2f}" + (f" {currency}" if currency else "")
        return f"{value:,.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"
    if isinstance(value, list):
        return ", ".join(shown(v, money=money, currency=currency) for v in cast(list[Any], value))
    if isinstance(value, dict):
        return ", ".join(
            f"{humanize(str(k)).lower()} {shown(v, money=False, currency=None)}"
            for k, v in cast(dict[str, Any], value).items()
        )
    return "" if value is None else str(value)


def object_rows(label: str, value: dict[str, Any]) -> list[dict[str, str]]:
    """An object the call sends as rows a person reads (c-565): one row per field, named "Fields · Status", so an
    approver sees each value the call would change rather than a raw object, or nothing at all."""
    rows: list[dict[str, str]] = []
    for k, v in value.items():
        shown_v = shown(v, money=False, currency=None)
        if shown_v:
            rows.append({"label": f"{label} · {humanize(str(k))}", "value": shown_v})
    return rows


# Each operation the tool directory lists, by name: its input schema and description.
# Each operation's input schema, description and title (a plugin tool's, c-581; None for others).
Operations = dict[str, tuple[dict[str, Any], str, str | None]]
_UNREAD: Any = object()


# The directory as this request already read it, keyed by the runtime; None outside a request (a worker, a test that
# calls a describer directly), where every call reads it.
_READ: ContextVar[dict[int, Operations | None] | None] = ContextVar("tool_directory_read", default=None)


class OneDirectoryRead:
    """ASGI middleware: a request reads the tool directory at most once, its streamed body included, however many
    calls its page or stream words (Human Tasks lists, chat widgets, Activity). Plain ASGI rather than
    BaseHTTPMiddleware, whose streamed body runs after the request's context has closed."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        token = _READ.set({})
        try:
            await self.app(scope, receive, send)
        finally:
            _READ.reset(token)


async def operations(rt: Runtime) -> Operations | None:
    """The tool directory's operations, read at most once per request (OneDirectoryRead) for every call it words;
    None when the registry is down."""
    seen = _READ.get()
    if seen is not None and id(rt) in seen:
        return seen[id(rt)]
    try:
        found: Operations | None = {
            # A directory that predates titles (or a test's stand-in) has none.
            op.name: (dict(op.input_schema or {}), str(op.description or ""), getattr(op, "title", None))
            for op in await rt.directory().operations()
        }
    except (ServiceCallError, ServiceUnreachable):
        found = None
    if seen is not None:
        seen[id(rt)] = found
    return found


def _operation(rt: Runtime, tool: str, ops: Operations | None) -> tuple[dict[str, Any], str]:
    """The operation's input schema and description from the tool directory, or the catalog's; empty when neither
    knows the tool. With the registry down the catalog's schema, or the call's own keys, word it instead of failing."""
    if ops and tool in ops:
        return ops[tool][:2]
    d = rt.catalog.tool(tool)
    return (dict(d.input_schema), d.description) if d else ({}, "")


async def tool_titles(rt: Runtime) -> dict[str, str]:
    """Each titled operation's title (a plugin tool's, c-581) for a chat card's wording; none while the directory
    cannot be read, so a card then reads by the operation's name rather than failing the reply."""
    try:
        ops = await operations(rt)
    except ApiError:
        return {}
    return {name: title for name, (_, _, title) in (ops or {}).items() if title}


def call_label(catalog: Any, call: dict[str, Any], titles: Mapping[str, str] | None = None) -> str:
    """The call's action in words, short ("Hold 2,140.55 on CHQ-2219", "Look up accounts"): the catalogue's approval
    action filled from the call, else the operation's name made readable. Needs no directory read, so a chat widget
    words its call as describe_call's `label` does."""
    tool = str(call.get("tool") or "")
    args = cast(dict[str, Any], call.get("input") or {})
    values = {_norm(k): shown(v, money=False, currency=None) for k, v in args.items()}
    template = (d := catalog.tool(tool)) and d.approval
    if template:
        filled = _PLACEHOLDER.sub(lambda m: values.get(_norm(m.group(1)), m.group(0)), template.action)
        if not _PLACEHOLDER.search(filled):
            return filled
    if titles and tool in titles:
        return titles[tool]
    return humanize(tool) if tool else "Run the step"


async def describe_calls(rt: Runtime, calls: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each call in words (describe_call), keyed as given, with the tool directory read once for all of them."""
    ops = await operations(rt) if calls else None
    return {k: await describe_call(rt, c, currency=None, money_key=None, ops=ops) for k, c in calls.items()}


async def describe_call(
    rt: Runtime, call: dict[str, Any], *, currency: str | None, money_key: str | None, ops: Any = _UNREAD
) -> dict[str, Any]:
    """One call in words: `label` (the action, short), `sentence` (the action with its values), `consequence`, and
    `fields` [{label, value}]. `money_key` is the input the review reads as its amount (typed_fields), shown with the
    account's currency. `ops` is the directory already read (describe_calls); unread, it is read for this call."""
    tool = str(call.get("tool") or "")
    args = cast(dict[str, Any], call.get("input") or {})
    ops_now = cast(Operations | None, await operations(rt) if ops is _UNREAD else ops)
    schema, description = _operation(rt, tool, ops_now)
    props = cast(dict[str, Any], schema.get("properties") or {})
    titles = {
        _norm(k): str(cast(dict[str, Any], p).get("title") or humanize(k))
        for k, p in props.items()
        if isinstance(p, dict)
    }
    values = {
        _norm(k): shown(v, money=money_key is not None and _norm(k) == _norm(money_key), currency=currency)
        for k, v in args.items()
    }

    def fill(template: str) -> str:
        return _PLACEHOLDER.sub(lambda m: values.get(_norm(m.group(1)), m.group(0)), template)

    # The operation's own description says what running it does; its first sentence is enough.
    said = description.strip().split(". ")[0].rstrip(".")
    template = (d := rt.catalog.tool(tool)) and d.approval
    # A call missing a value its template names (a failed call, a list row) reads as the plain wording below rather
    # than with "{amount}" left in it.
    if template and not _PLACEHOLDER.search(fill(template.action) + fill(template.title)):
        fields = [{"label": label, "value": fill(value)} for label, value in template.fields]
        return {
            "label": fill(template.action),
            "sentence": fill(template.title),
            # A card without a consequence line says what approving does by its operation's description.
            "consequence": template.consequence or (f"{said}." if said else None),
            "fields": fields,
        }
    # An object in the input (a webhook's payload) is data the call carries, read in the step's details; flattened into
    # the sentence it reads as a run of ids and keys.
    fields = [
        {"label": titles.get(_norm(k), humanize(k)), "value": values[_norm(k)]}
        for k, v in args.items()
        if values.get(_norm(k)) and not _MACHINE_ID.match(values[_norm(k)]) and not _object(v)
    ]
    named = ops_now[tool][2] if ops_now and tool in ops_now else None
    label = named or (humanize(tool) if tool else "Run the step")
    sentence = f"{label}: " + ", ".join(f"{f['label'].lower()} {f['value']}" for f in fields) if fields else label
    # An object the call writes (a record's changed fields) is what the approver decides on: its fields are rows of
    # the card, though never part of the sentence.
    for k, v in args.items():
        if _object(v):
            rows = object_rows(titles.get(_norm(k), humanize(k)), cast(dict[str, Any], v))
            fields += [r for r in rows if not _MACHINE_ID.match(r["value"])]
    return {"label": label, "sentence": sentence, "consequence": f"{said}." if said else None, "fields": fields}


def _object(value: Any) -> bool:
    return isinstance(value, dict) or (
        isinstance(value, list) and any(isinstance(v, dict) for v in cast(list[Any], value))
    )


def question(*, options: list[str], first: dict[str, Any] | None, customer: str, title: str) -> str:
    """The one question a step asks: which option, for whom, when it offers options; otherwise whether to run its
    call; otherwise the step's own title."""
    if len(options) > 1:
        words = [options[0], *(o[:1].lower() + o[1:] for o in options[1:])]
        choice = f"{', '.join(words[:-1])} or {words[-1]}"
        # Who it is about when the step names a customer; otherwise what it is, from the step's title.
        return f"{choice} for {customer}?" if customer else f"{title}: {choice[:1].lower()}{choice[1:]}?"
    if first is not None:
        return f"{first['sentence']}?"
    return title


def source_file(*values: Any) -> str | None:
    """The first file id in what the run was given or the step shows, breadth first: the document the decision is
    about, whatever key the workflow gave it."""
    queue = list(values)
    for _ in range(500):
        if not queue:
            return None
        v = queue.pop(0)
        if isinstance(v, str) and _FILE_ID.match(v):
            return v
        if isinstance(v, dict):
            queue.extend(cast(dict[str, Any], v).values())
        elif isinstance(v, list):
            queue.extend(cast(list[Any], v))
    return None
