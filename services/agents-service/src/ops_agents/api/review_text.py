"""A paused step's calls in words a reviewer reads (c-289): the question the step asks, what each option does, and
the values each call would send, without tool names, raw keys or raw floats. A tool's reviewer card template
(catalog `approval`) words it when there is one; any other operation is worded from its input schema's titles. The
same functions word every workflow's review, so nothing here knows one use case."""

from __future__ import annotations

import re
from typing import Any, cast

from ops_identity import ServiceCallError, ServiceUnreachable

from .deps import Runtime

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


async def _operation(rt: Runtime, tool: str) -> tuple[dict[str, Any], str]:
    """The operation's input schema and description from the tool directory, or the catalog's; empty when neither
    knows the tool."""
    try:
        for op in await rt.directory().operations():
            if op.name == tool:
                return dict(op.input_schema or {}), str(op.description or "")
    except (ServiceCallError, ServiceUnreachable):
        pass  # the registry is down: the catalog's schema, or the call's own keys, word it instead of failing the list
    d = rt.catalog.tool(tool)
    return (dict(d.input_schema), d.description) if d else ({}, "")


async def describe_call(
    rt: Runtime, call: dict[str, Any], *, currency: str | None, money_key: str | None
) -> dict[str, Any]:
    """One call in words: `label` (the action, short), `sentence` (the action with its values), `consequence`, and
    `fields` [{label, value}]. `money_key` is the input the review reads as its amount (typed_fields), shown with the
    account's currency."""
    tool = str(call.get("tool") or "")
    args = cast(dict[str, Any], call.get("input") or {})
    schema, description = await _operation(rt, tool)
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
    if template:
        fields = [{"label": label, "value": fill(value)} for label, value in template.fields]
        return {
            "label": fill(template.action),
            "sentence": fill(template.title),
            # A card without a consequence line says what approving does by its operation's description.
            "consequence": template.consequence or (f"{said}." if said else None),
            "fields": fields,
        }
    fields = [
        {"label": titles.get(_norm(k), humanize(k)), "value": values[_norm(k)]}
        for k in args
        if values.get(_norm(k)) and not _MACHINE_ID.match(values[_norm(k)])
    ]
    label = humanize(tool) if tool else "Run the step"
    sentence = f"{label}: " + ", ".join(f"{f['label'].lower()} {f['value']}" for f in fields) if fields else label
    return {"label": label, "sentence": sentence, "consequence": f"{said}." if said else None, "fields": fields}


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
