"""What the connection use cases share (c-330): the bank stand-in's hosts allowed, a connection set up per environment
as a person sets it in the console, a published one-operation module that signs in through it, and a call made the way
agents-service makes one. Every setup call's status is checked, so a refused setup fails the use case."""

from __future__ import annotations

import json
from typing import Any

import httpx
from usecase_harness import approve_tool_review, check, data, service_headers

SECURITY = {"X-Dev-User": "Nadia Petrov"}


def allow_bank(gw: httpx.Client, bank: dict[str, Any], *hosts: str) -> None:
    for host in (bank["host"], *hosts):
        gw.post("/v1/egress/hosts", json={"value": host, "note": "connection use case"})
    gw.post("/v1/egress/ranges", json={"value": bank["range"], "note": "connection use case"})


def clean(gw: httpx.Client, prefix: str) -> None:
    """Leaves nothing from an earlier run on a kept database: the modules first, then the connections they used."""
    for m in data(gw.get("/v1/tool-modules", params={"search": prefix, "pageSize": 50}))["data"]:
        gw.delete(f"/v1/tool-modules/{m['id']}")
    for c in data(gw.get("/v1/connections", params={"search": prefix, "pageSize": 50}))["data"]:
        gw.delete(f"/v1/connections/{c['id']}")


def connection(
    gw: httpx.Client, name: str, kind: str, environments: dict[str, dict[str, Any]], *, base_url: str
) -> dict[str, Any]:
    """A connection with each environment's `{"settings": ..., "secretValues": ...}` set, as a person sets them, each
    bound to `base_url`, the system its credentials may go to."""
    made = gw.post("/v1/connections", json={"name": name, "authKind": kind})
    check(f"connection {name} created (201)", made.status_code == 201, made.text[:300])
    conn = data(made)
    for env, body in environments.items():
        given = {**body, "settings": {"baseUrl": base_url, **(body.get("settings") or {})}}
        res = gw.put(f"/v1/connections/{conn['id']}/environments/{env}", json={"revision": conn["revision"], **given})
        check(f"connection {name} {env} set (200)", res.status_code == 200, res.text[:300])
        conn = data(res) or conn
    return conn


def module(
    gw: httpx.Client,
    name: str,
    url: str,
    connection_id: str | None,
    *,
    access: str = "read",
    method: str = "GET",
    at_once: bool = False,
    security: dict[str, str] = SECURITY,
) -> dict[str, Any]:
    """A published module of one hand-built http operation named `name`, signing in through `connection_id`. A write
    with `at_once` runs without an approval, as the levy webhook does. `security` is who approves its review: a
    Security approver's headers (a dev name, or a token when the stack verifies platform tokens)."""
    body = {
        "name": name,
        "displayName": name,
        "system": "Bank stand-in",
        "type": "http",
        "endpoint": "",
        "connectionId": connection_id,
        "http": {"name": name.replace("-", "_"), "description": name, "access": access, "method": method, "url": url},
    }
    made = gw.post("/v1/tool-modules", json=body)
    check(f"module {name} created (201)", made.status_code == 201, made.text[:300])
    m = data(made)
    if at_once:
        op = m["operations"][0]
        res = gw.patch(f"/v1/tool-modules/{m['id']}/operations/{op['id']}", json={"requiresApproval": False})
        check(f"module {name} runs at once", res.status_code == 200, res.text[:300])
    asked = gw.post(f"/v1/tool-modules/{m['id']}/reviews", json={"note": "connection use case"})
    check(f"module {name} review requested", asked.status_code in (200, 201), asked.text[:300])
    published = approve_tool_review(gw, m["id"], security)
    check(f"module {name} published", published.get("status") == "published", published)
    return published


def bank_control(bank: dict[str, Any], path: str, *, method: str = "GET") -> dict[str, Any]:
    """The stand-in's test controls (token stats, revoking access tokens), reached at its address directly."""
    address = json.loads(bank["settings"]["OPS_EGRESS_RESOLVE"])[bank["host"]]
    res = httpx.request(method, f"https://{address}{path}", verify=False, timeout=10)
    return dict(res.json())


def call(
    gw: httpx.Client,
    tool: str,
    *,
    environment: str | None = None,
    key: str | None = None,
    token: str | None = None,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The gateway's answer to a call as agents-service sends one, in `environment` (none: the field left out)."""
    context: dict[str, Any] = {"act": "workflow:connection_usecase"}
    if environment is not None:
        context["environment"] = environment
    body = {"tool": tool, "input": args or {}, "key": key or f"{tool}-{environment}", "runContext": context}
    if token is not None:
        body["approvalToken"] = token
    res = gw.post("/v1/calls", json=body, headers=service_headers("tools"))
    return data(res) if res.status_code == 200 else {"status": res.status_code, "text": res.text[:300]}
