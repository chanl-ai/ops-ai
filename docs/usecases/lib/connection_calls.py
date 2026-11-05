"""What the connection use cases share: the bank stand-in's hosts allowed, a custom app with its live account and,
where asked, a sandbox account, set up as a person sets them in the console, a published one-operation module that
signs in through it, and a call made the way agents-service makes one. Every setup call's status is checked, so a
refused setup fails the use case."""

from __future__ import annotations

import json
from typing import Any

import httpx
from usecase_harness import approve_tool_review, check, data, service_headers

SECURITY = {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}


def allow_bank(gw: httpx.Client, bank: dict[str, Any], *hosts: str) -> None:
    for host in (bank["host"], *hosts):
        gw.post("/v1/egress/hosts", json={"value": host, "note": "connection use case"})
    gw.post("/v1/egress/ranges", json={"value": bank["range"], "note": "connection use case"})


def clean(gw: httpx.Client, prefix: str) -> None:
    """Leaves nothing from an earlier run on a kept database: the modules first, then the apps they used, each app's
    other accounts before its first."""
    for m in data(gw.get("/v1/tool-modules", params={"search": prefix, "pageSize": 50}))["data"]:
        gw.delete(f"/v1/tool-modules/{m['id']}")
    for card in data(gw.get("/v1/apps")) or []:
        if card.get("kind") != "connection" or prefix.lower() not in str(card.get("name", "")).lower():
            continue
        app = str(card["id"])
        accounts = [a for c in (data(gw.get(f"/v1/apps/{app}")) or {}).get("authConfigs") or [] for a in c["accounts"]]
        for a in sorted(accounts, key=lambda a: a["id"] == app):
            gw.delete(f"/v1/apps/{app}/accounts/{a['id']}")


def at(account: dict[str, Any]) -> str:
    """An account's address under its app."""
    return f"/v1/apps/{account['appId']}/accounts/{account['id']}"


def _keys(gw: httpx.Client, account: dict[str, Any], body: dict[str, Any], base_url: str, what: str) -> dict[str, Any]:
    given = {**body, "settings": {"baseUrl": base_url, **(body.get("settings") or {})}}
    res = gw.patch(at(account), json={"revision": account["revision"], **given})
    check(f"{what} set (200)", res.status_code == 200, res.text[:300])
    return data(res) or account


def connection(
    gw: httpx.Client, name: str, kind: str, accounts: dict[str, dict[str, Any]], *, base_url: str
) -> dict[str, Any]:
    """A custom app and its accounts, each `{"settings": ..., "secretValues": ...}` set as a person sets them and bound
    to `base_url`, the system its credentials may go to: `live` is the app's first account, `sandbox` a sandbox account
    beside it (the one test runs use). With only a sandbox, the app's first account is that sandbox. The answer is the
    first account, with the sandbox account under `sandboxAccount` when both were made."""
    only_sandbox = "live" not in accounts
    made = gw.post("/v1/apps", json={"name": name, "authKind": kind, "sandbox": only_sandbox})
    check(f"app {name} created (201)", made.status_code == 201, made.text[:300])
    first = _keys(gw, data(made), accounts["sandbox" if only_sandbox else "live"], base_url, f"app {name}")
    if only_sandbox or "sandbox" not in accounts:
        return first
    added = gw.post(f"/v1/apps/{first['id']}/accounts", json={"name": f"{name} sandbox", "sandbox": True})
    check(f"app {name} sandbox account added (201)", added.status_code == 201, added.text[:300])
    sandbox = _keys(gw, data(added), accounts["sandbox"], base_url, f"app {name} sandbox")
    return {**first, "sandboxAccount": sandbox}


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
    op = m["operations"][0]
    # Approvals are off unless a tool turns them on, so a write made here usually runs at once already.
    if at_once and op.get("requiresApproval"):
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
