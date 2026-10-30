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


def at(data: Any, path: str) -> Any:
    """The value at a dotted path of an answer, or None."""
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = cast(dict[str, Any], node).get(part)
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


def arguments(tool: Tool, given: Mapping[str, Any], state: Mapping[str, Any] | None) -> dict[str, Any]:
    """What a call sends besides its path: the checked inputs no query template takes, each query parameter rendered,
    and the page's token or offset. InputRefused for a value its input does not allow."""
    req = tool.request
    assert req is not None
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
    return sent


def next_page(paging: Paging | None, answer: Any, offset: int) -> tuple[Any, dict[str, Any]]:
    """The answer without the system's own page address, and the next page's state: {} on the last page."""
    if paging is None:
        return answer, {}
    if paging.rule in ("link", "token") and paging.next:
        value = at(answer, paging.next)
        found = {("link" if paging.rule == "link" else "token"): str(value)} if value else {}
        return without(answer, paging.next), found
    rows = at(answer, str(paging.items))
    if isinstance(rows, list) and paging.limit and len(cast(list[Any], rows)) >= paging.limit:
        return answer, {"offset": offset + paging.limit}
    return answer, {}


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
