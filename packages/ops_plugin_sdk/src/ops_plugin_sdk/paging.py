"""What a data tool sends and how it reaches its next page, shared by tools-service and `ops plugin test`, so a plugin
is tested the way it runs.

A call's arguments are checked against the tool's inputs, the query templates are rendered from the checked values
(formats.py), and an input a query uses is not also sent on its own. A page's answer names the next page by an
address (`link`), a token (`token`) or nothing at all, the next offset following from a full page (`offset`); the
next page is kept as a small state with the first call's arguments, which tools-service seals before it leaves. A
link is followed alone: a GET to that address carrying none of the first call's parameters or body."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, cast
from urllib.parse import urlsplit

from .formats import check, render
from .manifest import Paging, Tool

QUERY_VAR = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


PATH_STEP = re.compile(r"\.?([^.\[\]]+)|\[(\d+)\]")


def steps(path: str) -> list[str | int] | None:
    """A path's steps: `urls.custom_domain`, `[0].id`, `.accounts[0].base_uri`; None when it does not parse."""
    out: list[str | int] = []
    at_ = 0
    while at_ < len(path):
        m = PATH_STEP.match(path, at_)
        if m is None or (m.group(1) is not None and out and not m.group(0).startswith(".")):
            return None
        out.append(m.group(1) if m.group(1) is not None else int(m.group(2)))
        at_ = m.end()
    return out or None


def at(data: Any, path: str) -> Any:
    """The value at a path of an answer, keys and list indexes (`.accounts[0].base_uri`), or None."""
    node: Any = data
    for step in steps(path) or [None]:
        if isinstance(step, int):
            if not isinstance(node, list) or step >= len(cast(list[Any], node)):
                return None
            node = cast(list[Any], node)[step]
        elif isinstance(node, dict) and step is not None:
            node = cast(dict[str, Any], node).get(step)
        else:
            return None
    return node


def without(data: Any, path: str) -> Any:
    """The answer without the field at a dotted path, as the system's own page address leaves only sealed."""
    head, _, rest = path.partition(".")
    if not isinstance(data, dict):
        return data
    answer = dict(cast(dict[str, Any], data))
    if head not in answer:
        return answer
    if rest:
        answer[head] = without(answer[head], rest)
    else:
        answer.pop(head)
    return answer


def in_query(tool: Tool) -> set[str]:
    req = tool.request
    return {n for t in (req.query.values() if req else ()) for n in QUERY_VAR.findall(t)}


SETTING = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def with_defaults(tool: Tool, given: Mapping[str, Any]) -> dict[str, Any]:
    """The call's inputs with each declared `default` in the place of an input it leaves out."""
    filled = {n: f.default for n, f in tool.input.items() if f.default is not None and given.get(n) is None}
    return {**dict(given), **filled}


def headers(plugin_headers: Mapping[str, str], tool: Tool, settings: Mapping[str, Any]) -> dict[str, str]:
    """A call's headers: the plugin's, then the tool's over them, `{setting}` rendered from the call's settings. A
    header whose setting is unset is left out. The connection's sign-in is added after these and wins a shared name."""
    out: dict[str, str] = {}
    for name, template in {**plugin_headers, **tool.headers}.items():
        if any(settings.get(n) in (None, "") for n in SETTING.findall(template)):
            continue
        out[name] = SETTING.sub(lambda m: str(settings[m.group(1)]), template)
    return out


def arguments(tool: Tool, given: Mapping[str, Any], state: Mapping[str, Any] | None) -> dict[str, Any]:
    """What a call sends besides its path: the checked inputs no query template takes, each query parameter rendered,
    and the page's token or offset; an input left out takes its default. InputRefused for a value its input does not
    allow."""
    req = tool.request
    assert req is not None
    given = with_defaults(tool, given)
    values = {n: check(tool.input[n], v, n) for n, v in given.items() if n in tool.input}
    used = in_query(tool)
    sent: dict[str, Any] = {
        n: render(tool.input[n], v) if isinstance(v, (date, datetime)) else v
        for n, v in values.items()
        if n not in used
    }
    for name, template in req.query.items():
        sent[name] = QUERY_VAR.sub(
            lambda m: render(tool.input[m.group(1)], values[m.group(1)]) if m.group(1) in values else "", template
        )
    paging = req.paging
    if paging is not None and paging.rule == "token" and state is not None:
        sent[str(paging.param)] = state.get("token")
    elif paging is not None and paging.rule == "offset":
        sent[paging.offset_param] = int((state or {}).get("offset") or 0)
        sent[paging.limit_param] = paging.limit
    elif paging is not None and paging.rule == "page":
        sent[paging.param or "page"] = int((state or {}).get("page") or paging.start)
        sent[paging.limit_param] = paging.limit
    return sent


FOLLOWS_LINK = ("link", "link_header")
_LINK = re.compile(r"<([^>]*)>((?:\s*;\s*[^;,]+)*)")
_REL = re.compile(r"""rel\s*=\s*"?([^";]+)"?""", re.IGNORECASE)


def link_next(header: str) -> str | None:
    """The `rel="next"` address of an RFC 8288 Link header, or None."""
    for m in _LINK.finditer(header):
        rel = _REL.search(m.group(2))
        if rel and "next" in rel.group(1).lower().split():
            return m.group(1).strip()
    return None


def next_page(
    paging: Paging | None, answer: Any, sent: Mapping[str, Any], headers: Mapping[str, str] | None = None
) -> tuple[Any, dict[str, Any]]:
    """The answer without the system's own page address, and the next page's state: {} on the last page. `sent` is
    what the page was asked with; `headers` the answer's, for a Link header."""
    if paging is None:
        return answer, {}
    if paging.rule == "link_header":
        found = {k.lower(): v for k, v in (headers or {}).items()}.get("link")
        link = link_next(found) if found else None
        return answer, {"link": link} if link else {}
    if paging.rule in ("link", "token") and paging.next:
        value = at(answer, paging.next)
        found_state = {("link" if paging.rule == "link" else "token"): str(value)} if value else {}
        return without(answer, paging.next), found_state
    rows = at(answer, paging.items) if paging.items else answer
    full = isinstance(rows, list) and bool(paging.limit) and len(cast(list[Any], rows)) >= (paging.limit or 0)
    if not full or paging.limit is None:
        return answer, {}
    if paging.rule == "page":
        return answer, {"page": int(sent.get(paging.param or "page", paging.start)) + 1}
    return answer, {"offset": int(sent.get(paging.offset_param, 0)) + paging.limit}


def with_next(output: Any, cursor: str) -> dict[str, Any]:
    """The tool's answer with `next_cursor`; a list answer is kept under `records`."""
    page = dict(cast(dict[str, Any], output)) if isinstance(output, dict) else {"records": output}
    return {**page, "next_cursor": cursor}


def follow(endpoint: str, link: str) -> tuple[str, str] | None:
    """The origin and path a page address is sent to: a relative address joins the endpoint's origin, an absolute one
    keeps its host, which the caller checks against the plugin's hosts. Braces are encoded, so an address the system
    answered cannot name one of the tenant's secrets. None for an empty address or one on another scheme."""
    parts, base = urlsplit(link), urlsplit(endpoint)
    if not link or (parts.scheme and parts.scheme != base.scheme):
        return None
    origin = f"{parts.scheme}://{parts.netloc}" if parts.netloc else f"{base.scheme}://{base.netloc}"
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return origin, path.replace("{", "%7B").replace("}", "%7D")
