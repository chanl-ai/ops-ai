"""Runs a plugin's tools against its fake system, for the plugin's own tests and `opsai plugin test`.

It sends what tools-service sends for the same tool: the endpoint and path rendered with the settings and the
arguments, each input left out as its default, a body template's `{{arg}}` as JSON, the remaining arguments as the
query of a GET, the plugin's and the tool's headers, the bearer token, and a transform rendered over `data` and
`settings`. Every request is checked against the plugin's egress hosts first, as the
gateway does, so a test that passes here does not pass by reaching a host the plugin did not list. It is a developer's
check of the plugin's contract; the gateway, its approvals and its call log are tools-service's."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import quote, urlsplit

import httpx
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from . import paging
from .context import Context, Response
from .errors import EgressDenied, NeedsReconnect, RateLimited
from .knowledge import source_hosts, source_of
from .plugin import Plugin

PLACE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
BODY = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
_ENV = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)


def render(text: str, values: Mapping[str, Any], *, encode: bool = False) -> str:
    """`{name}` from `values`; URL-encoded for a path segment."""

    def one(m: re.Match[str]) -> str:
        if m.group(1) not in values:
            raise KeyError(f"{{{m.group(1)}}} has no value")
        value = str(values[m.group(1)])
        return quote(value, safe="") if encode else value

    return PLACE.sub(one, text)


def hosts(plugin: Plugin, settings: Mapping[str, Any]) -> list[str]:
    """The egress hosts, rendered with the settings: `{instance_url}` gives that URL's host."""
    out: list[str] = []
    for template in plugin.manifest.egress:
        rendered = render(template, settings)
        out.append(urlsplit(rendered).hostname or rendered)
    return out


@dataclass
class Fake:
    """Where the fake answers and the token it accepts; `client` may be bound to an in-process app."""

    client: httpx.Client
    token: str


def _send(fake: Fake, allowed: list[str], sent_headers: Mapping[str, str] | None = None) -> Any:
    def send(
        method: str, url: str, params: Mapping[str, Any] | None, body: Any, asked: Mapping[str, str] | None = None
    ) -> Response:
        host = urlsplit(url).hostname
        if host not in allowed:
            raise EgressDenied(f"{host} is not one of this plugin's hosts.")
        # The request's own headers, then the plugin's and the tool's, then the sign-in, which wins a name they share.
        out = {**dict(asked or {}), **dict(sent_headers or {}), "Authorization": f"Bearer {fake.token}"}
        # No params at all for a followed page address: an empty mapping would replace the query the address carries.
        r = fake.client.request(method, url, params=dict(params) if params else None, json=body, headers=out)
        if r.status_code == 401:
            raise NeedsReconnect("The system refused the sign-in.")
        if r.status_code == 429:
            raise RateLimited("The system's rate limit was reached.")
        return Response(r.status_code, r.text, dict(r.headers), r.content)

    return send


def settings_of(plugin: Plugin, given: Mapping[str, Any]) -> dict[str, Any]:
    """The plugin's defaults with `given` over them."""
    base = {k: s.default for k, s in plugin.manifest.settings.items() if s.default is not None}
    return {**base, **given}


def call(plugin: Plugin, tool: str, args: Mapping[str, Any], settings: Mapping[str, Any], fake: Fake) -> Any:
    """What `tool` answers for `args`, run as tools-service runs it."""
    t = plugin.manifest.tool(tool)
    if t is None:
        raise KeyError(f"{plugin.manifest.id} has no tool {tool}")
    merged = settings_of(plugin, settings)
    # A knowledge source's calls also reach the hosts of the addresses its own settings name (its egress_from input).
    source = source_of(plugin.manifest, tool)
    values = args.get("source") if isinstance(args.get("source"), Mapping) else None
    allowed = hosts(plugin, merged) + (source_hosts(source, values) if source else [])
    send = _send(fake, allowed, paging.headers(plugin.manifest.headers, t, merged))
    if t.function is not None:
        return plugin.function(tool)(Context.of(merged, send), **dict(args))
    assert t.request is not None
    req = t.request
    endpoint = render(plugin.manifest.endpoint, merged).rstrip("/")
    given = paging.with_defaults(t, args)
    # The cursor is the next page's state as tools-service keeps it, here unsealed: the test reads it back as given.
    cursor = given.pop("cursor", None) if req.paging is not None else None
    state: dict[str, Any] | None = json.loads(cursor) if cursor else None
    if state is not None:
        given = dict(state.get("args") or {})
    sent = paging.arguments(t, given, state)
    method, body = req.method, None
    params: dict[str, Any] | None = None
    if state is not None and req.paging is not None and req.paging.rule in paging.FOLLOWS_LINK:
        followed = paging.follow(endpoint, str(state.get("link") or ""))
        if followed is None:
            raise EgressDenied("The cursor holds no page address this plugin can follow.")
        url, method = followed[0] + followed[1], "GET"
    else:
        path = render(req.path, {**merged, **sent}, encode=True)
        used = set(PLACE.findall(req.path))
        rest = {k: v for k, v in sent.items() if k not in used}
        url = endpoint + path
        if req.body:
            body = json.loads(BODY.sub(lambda m: json.dumps(given.get(m.group(1))), req.body))
        elif method in ("GET", "DELETE"):
            params = rest
        else:
            body = rest
    r = send(method, url, params, body, None)
    if r.status_code >= 400:
        raise RuntimeError(f"{tool} answered {r.status_code}: {r.text[:200]}")
    data: Any = r.json() if r.text else None
    data, found = paging.next_page(req.paging, data, sent, r.headers)
    out: Any = data
    if t.transform:
        text = _ENV.from_string(t.transform).render(data=data, settings=merged)
        try:
            out = json.loads(text)
        except ValueError:
            out = text
    return paging.with_next(out, json.dumps({**found, "args": given})) if found else out


def _items(page: Any) -> list[dict[str, Any]] | None:
    if not isinstance(page, dict):
        return None
    rows = cast(dict[str, Any], page).get("items")
    if not isinstance(rows, list):
        return None
    return [cast(dict[str, Any], r) for r in cast(list[Any], rows) if isinstance(r, dict)]


def _list_all(
    plugin: Plugin, tool: str, args: Mapping[str, Any], settings: Mapping[str, Any], fake: Fake
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Every item a listing or changes tool gives, page by page, its last page, and what is wrong with its pages."""
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    cursor: str | None = None
    last: dict[str, Any] = {}
    for _ in range(100):
        page = call(plugin, tool, {**args, **({"cursor": cursor} if cursor else {})}, settings, fake)
        rows = _items(page)
        if rows is None:
            problems.append(f"{tool} did not answer {{items: [...]}}")
            break
        for r in rows:
            if not {"id", "updated_at"} <= set(r):
                problems.append(f"{tool} gave an item without id and updated_at: {sorted(r)}")
        out += rows
        last = cast(dict[str, Any], page)
        cursor = last.get("next_cursor")
        if not cursor:
            break
    return out, last, problems


def knowledge_contract(
    plugin: Plugin,
    source: str,
    fake: Fake,
    *,
    settings: Mapping[str, Any],
    values: Mapping[str, Any] | None = None,
    change: Callable[[], str],
    delete: Callable[[], str],
) -> list[str]:
    """What a knowledge-source plugin must do for kb-service to sync it, run against its fake system: list every item,
    fetch one with its content, answer `unchanged` for a version tag that still matches, find an item `change` changed
    (through its changes tool, or by listing since the watermark), and find an item `delete` removed (through its
    deleted tool, or by its absence from a full listing). `change` and `delete` act on the fake and return the item's
    id. The answer is the list of problems; empty means the plugin passes."""
    found = next((s for s in plugin.manifest.knowledge_sources if s.name == source), None)
    if found is None:
        return [f"{plugin.manifest.id} offers no knowledge source {source}"]
    given: dict[str, Any] = {"source": dict(values)} if values is not None else {}
    items, last, problems = _list_all(plugin, found.list, given, settings, fake)
    if not items:
        return [*problems, f"{found.list} listed nothing to check"]
    first = items[0]
    got = call(plugin, found.get, {**given, "id": first["id"]}, settings, fake)
    if not isinstance(got, dict) or "content" not in got:
        problems.append(f"{found.get} gave no content for {first['id']}")
    else:
        fetched = cast(dict[str, Any], got)
        if not fetched.get("mime"):
            problems.append(f"{found.get} gave no mime for {first['id']}")
        allowed = fetched.get("allowed")
        if allowed is not None and not isinstance(allowed, list):
            problems.append(f"{found.get} gave allowed that is not a list of ids")
        tag = fetched.get("marker") or first.get("marker")
        get_tool = plugin.manifest.tool(found.get)
        if tag and get_tool is not None and "tag" in get_tool.input:
            again = call(plugin, found.get, {**given, "id": first["id"], "tag": tag}, settings, fake)
            if not (isinstance(again, dict) and cast(dict[str, Any], again).get("unchanged") is True):
                problems.append(f"{found.get} fetched {first['id']} again though its tag {tag} still matches")
    changed = change()
    if found.changes is not None:
        cursor = last.get("cursor") or last.get("watermark")
        rows, _, more = _list_all(
            plugin, found.changes, {**given, "cursor": cursor} if cursor else given, settings, fake
        )
    else:
        since = last.get("watermark")
        rows, _, more = _list_all(plugin, found.list, {**given, "since": since} if since else given, settings, fake)
    problems += more
    if changed not in {str(r["id"]) for r in rows}:
        problems.append(f"the change to {changed} was not found")
    gone = delete()
    if found.deleted is not None:
        answer = call(plugin, found.deleted, {**given, "since": str(first.get("updated_at") or "")}, settings, fake)
        listed = cast(list[Any], cast(dict[str, Any], answer).get("ids") or []) if isinstance(answer, dict) else []
        ids = {str(i) for i in listed}
        if gone not in ids:
            problems.append(f"{found.deleted} did not report {gone} as deleted")
    else:
        rows, _, more = _list_all(plugin, found.list, given, settings, fake)
        problems += more
        if gone in {str(r["id"]) for r in rows}:
            problems.append(f"{gone} is still listed after it was deleted")
    return problems
