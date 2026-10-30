"""Runs a plugin's tools against its fake system, for the plugin's own tests and `ops plugin test`.

It sends what tools-service sends for the same tool: the endpoint and path rendered with the settings and the
arguments, a body template's `{{arg}}` as JSON, the remaining arguments as the query of a GET, the bearer token, and a
transform rendered over `data` and `settings`. Every request is checked against the plugin's egress hosts first, as the
gateway does, so a test that passes here does not pass by reaching a host the plugin did not list. It is a developer's
check of the plugin's contract; the gateway, its approvals and its call log are tools-service's."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from . import paging
from .context import Context, Response
from .errors import EgressDenied, NeedsReconnect, RateLimited
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


def _send(fake: Fake, allowed: list[str]) -> Any:
    def send(method: str, url: str, params: Mapping[str, Any] | None, body: Any) -> Response:
        host = urlsplit(url).hostname
        if host not in allowed:
            raise EgressDenied(f"{host} is not one of this plugin's hosts.")
        r = fake.client.request(
            method, url, params=dict(params or {}), json=body, headers={"Authorization": f"Bearer {fake.token}"}
        )
        if r.status_code == 401:
            raise NeedsReconnect("The system refused the sign-in.")
        if r.status_code == 429:
            raise RateLimited("The system's rate limit was reached.")
        return Response(r.status_code, r.text, dict(r.headers))

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
    send = _send(fake, hosts(plugin, merged))
    if t.function is not None:
        return plugin.function(tool)(Context.of(merged, send), **dict(args))
    assert t.request is not None
    req = t.request
    endpoint = render(plugin.manifest.endpoint, merged).rstrip("/")
    given = dict(args)
    # The cursor is the next page's state as tools-service keeps it, here unsealed: the test reads it back as given.
    cursor = given.pop("cursor", None) if req.paging is not None else None
    state: dict[str, Any] | None = json.loads(cursor) if cursor else None
    if state is not None:
        given = dict(state.get("args") or {})
    sent = paging.arguments(t, given, state)
    method, body = req.method, None
    params: dict[str, Any] | None = None
    if state is not None and req.paging is not None and req.paging.rule == "link":
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
    r = send(method, url, params, body)
    if r.status_code >= 400:
        raise RuntimeError(f"{tool} answered {r.status_code}: {r.text[:200]}")
    data: Any = r.json() if r.text else None
    offset = int(sent.get(req.paging.offset_param, 0)) if req.paging and req.paging.rule == "offset" else 0
    data, found = paging.next_page(req.paging, data, offset)
    out: Any = data
    if t.transform:
        text = _ENV.from_string(t.transform).render(data=data, settings=merged)
        try:
            out = json.loads(text)
        except ValueError:
            out = text
    return paging.with_next(out, json.dumps({**found, "args": given})) if found else out
