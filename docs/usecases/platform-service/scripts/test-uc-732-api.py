"""uc-732 a team admin gives a system its own expiring, rotatable key limited to picked tools, and the call log names
that system, api layer: docs/usecases/platform-service/a-team-admin-gives-a-system.md. platform-service issues the
keys and tools-service verifies them through its introspection. No model call."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any

import httpx
from usecase_harness import (
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    TOOLS_PORT,
    bearer,
    check,
    data,
    finish,
    invited,
    platform,
    signed_in,
    tools,
    until,
)

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
PICKED, OTHER_READ, WRITE = "get_loan_account", "lookup_account", "transfer_funds"


def call(gw: httpx.Client, secret: str, tool: str, step: str) -> httpx.Response:
    secret = secret or "ok_key_missing.nothing"  # a step after a failed make still sends a well-formed header
    body = {"tool": tool, "input": {}, "key": f"uc721-{step}", "runContext": {"environment": "test", "act": "key"}}
    return gw.post("/v1/calls", json=body, headers={"Authorization": f"Bearer {secret}"})


def body_of(r: httpx.Response) -> dict[str, Any]:
    """The data of an answer that succeeded, else an empty map, so a step after a refused one reports its own failure."""
    return (data(r) if r.status_code < 400 else {}) or {}


def refused_as_scope(r: httpx.Response) -> bool:
    return "insufficient_scope" in r.text


with ExitStack() as stack:
    api, _ = stack.enter_context(platform())
    gw = stack.enter_context(
        httpx.Client(
            base_url=f"http://127.0.0.1:{TOOLS_PORT}",
            timeout=30,
        )
    )
    stack.enter_context(tools(AUTH))
    priya = bearer(signed_in(api, "p.shah@harborpine.example"), "team_ops")
    james = bearer(signed_in(api, "j.richardson@harborpine.example"), "team_ops")

    # Step 1: who may make a key, and that it always ends.
    body: dict[str, Any] = {"name": "Claims triage script", "scopes": ["read"], "tools": [PICKED], "expiresInDays": 90}
    # Bodies without `tools`, so a refusal is for the expiry or the role and not for a field the service does not know yet.
    plain = {k: v for k, v in body.items() if k != "tools"}
    check("1 a builder is refused a key (403)", api.post("/v1/api-keys", headers=james, json=plain).status_code == 403)
    for why, bad in (
        ("no expiry", {k: v for k, v in plain.items() if k != "expiresInDays"}),
        ("366 days", plain | {"expiresInDays": 366}),
    ):
        r = api.post("/v1/api-keys", headers=priya, json=bad)
        check(f"1 an admin gets a 4xx for {why}", r.status_code in (400, 422), r.text[:160])
    r = api.post("/v1/api-keys", headers=priya, json=body)
    made = body_of(r)
    secret, key_id = made.get("secret", ""), (made.get("key") or {}).get("id", "key_missing")
    check(
        "1 an admin makes the key and sees its secret once",
        r.status_code == 201 and secret.startswith("ok_"),
        r.text[:200],
    )

    # Step 2: the picked tool runs, another does not, and the log names the key.
    own = call(gw, secret, PICKED, "own")
    other = call(gw, secret, OTHER_READ, "other")
    check(
        "2 the key is refused a read it was not given with insufficient_scope",
        refused_as_scope(other),
        other.text[:200],
    )
    check(
        "2 the picked tool passes the tool limit", own.status_code != 401 and not refused_as_scope(own), own.text[:200]
    )
    rows = body_of(gw.get("/v1/executions", params={"pageSize": 20}, headers=priya)).get("data", [])
    text = str([r for r in rows if r.get("tool") == PICKED])
    check(
        "2 the call log names the key, its name and its maker, not Priya as the caller",
        f"key:{key_id}" in text and "Claims triage script" in text and "p.shah@harborpine.example" in text,
        text[:300],
    )

    # Step 3: a write by a key is refused as a scope error and holds nothing.
    writer = body_of(
        api.post("/v1/api-keys", headers=priya, json={**body, "name": "Closer", "tools": [PICKED, WRITE]})
    ).get("secret", "")
    w = call(gw, writer, WRITE, "write")
    check(
        "3 a write by a key is refused with insufficient_scope and opens no hold",
        refused_as_scope(w) and "approval" not in w.text.lower(),
        w.text[:200],
    )

    # Step 4: rotation. The new secret works, the old one lives through the grace, stop-now ends it within the cache.
    r = api.post(f"/v1/api-keys/{key_id}/rotate", headers=priya, json={})
    fresh = body_of(r).get("secret", "")
    check("4 Rotate answers a new secret", r.status_code == 200 and fresh != secret, r.text[:200])
    check("4 the old secret still works in the grace", call(gw, secret, PICKED, "grace-old").status_code != 401)
    r = api.post(f"/v1/api-keys/{key_id}/rotate", headers=priya, json={"stopNow": True})
    newest = body_of(r).get("secret", "")
    check("4 Rotate with stop now answers a secret", r.status_code == 200 and bool(newest), r.text[:200])
    # ops_identity caches a key's answer for 30 seconds, so the old secret is refused within that time.
    ended = until(lambda: call(gw, fresh, PICKED, "stopped").status_code == 401, timeout=45)
    check("4 the stopped secret is refused within the key cache", bool(ended) and bool(newest) and bool(fresh))

    # Step 5: the key outlives its maker.
    ravi = invited(api, priya, "ravi.maker@harborpine.example", "admin")
    maker = {"Authorization": f"Bearer {ravi.get('token', '')}", "X-Team-Id": "team_ops"}
    theirs = body_of(api.post("/v1/api-keys", headers=maker, json={**body, "name": "Ravi's export"})).get("secret", "")
    members = body_of(api.get("/v1/settings/members", headers=priya)).get("data", [])
    row = next((m for m in members if m.get("email") == "ravi.maker@harborpine.example"), {})
    api.post("/v1/settings/members/delete", headers=priya, json={"ids": [row.get("id")]})
    after = call(gw, theirs, PICKED, "maker-gone")
    check("5 the key still works after its maker leaves the team", after.status_code != 401, after.text[:200])
    listed = body_of(api.get("/v1/api-keys", headers=priya))
    check("5 the keys list shows the maker as gone", any(k.get("makerGone") for k in listed), str(listed)[:200])

    # Step 6: a key that starts runs is still made, with its target.
    target = {"kind": "workflow", "id": "levy_intake", "version": 3}
    r = api.post(
        "/v1/api-keys",
        headers=priya,
        json={"name": "Run starter", "scopes": ["write"], "target": target, "expiresInDays": 365},
    )
    check(
        "6 a write key for a workflow is still made, with its target",
        r.status_code == 201 and body_of(r)["key"]["target"] == target,
        r.text[:200],
    )

finish()
