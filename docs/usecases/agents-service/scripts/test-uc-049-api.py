"""uc-049 a write runs only after as many people as its policy names approve it, api layer:
docs/usecases/agents-service/write-approval-policy.md. agents-service runs on the scripted model with tools-service as
its gateway; the write calls the fake bank on https, so "it ran" and "nothing ran" are checked on the bank's side."""

from __future__ import annotations

import json
import time
from typing import Any

from fake_bank_https import HOST, fake_bank
from usecase_harness import AGENTS_PORT, TEAM, TOOLS_PORT, agents, check, data, finish, service_headers, sse, tools

SECURITY = {"X-Dev-User": "Nadia Petrov"}
MAYA, PRIYA = {"X-Dev-User": "Maya Okafor"}, {"X-Dev-User": "Priya Shah"}
RUN = int(time.time())
WRITE = f"freeze_account_{RUN}"
ACCOUNT = "CHQ-2219"


def published_module(gw: Any) -> str:
    """A module with one write whose policy needs two approvers, reviewed and published."""
    made = data(
        gw.post(
            "/v1/tool-modules/blank", json={"displayName": f"Accounts {RUN}", "name": f"accounts-{RUN}", "type": "http"}
        )
    )
    mid = made["id"]
    added = gw.post(
        f"/v1/tool-modules/{mid}/operations",
        json={
            "name": WRITE,
            "description": "Freeze an account",
            "access": "write",
            "method": "POST",
            "url": f"https://{HOST}/v1/accounts/{{accountId}}/holds",
        },
    )
    op_id = next(o["id"] for o in data(added)["operations"] if o["name"] == WRITE)
    patched = gw.patch(f"/v1/tool-modules/{mid}/operations/{op_id}", json={"approvers": 2})
    check("the operation's policy is set to two approvers", patched.status_code == 200, patched.text[:200])
    reviewed = data(gw.post(f"/v1/tool-modules/{mid}/reviews", json={"note": "uc-049"}))
    review = next(r["id"] for r in reviewed["reviews"] if r["decision"] == "pending")
    gw.post(f"/v1/tool-modules/{mid}/reviews/{review}/decide", json={"decision": "approved"}, headers=SECURITY)
    return str(mid)


def step_up(api: Any, who: dict[str, str]) -> str:
    """A step-up for `who`: approving a write two people approve asks each of them to re-authenticate."""
    return str(
        data(api.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers={**TEAM, **who}))["token"]
    )


def holds(bank: Any) -> list[dict[str, Any]]:
    return [r for r in bank.received if r["method"] == "POST" and r["path"] == f"/v1/accounts/{ACCOUNT}/holds"]


settings = {"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}
with (
    fake_bank() as bank,
    agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}") as api,
    tools(settings={**bank.settings, **settings}) as gw,
):
    gw.post("/v1/egress/hosts", json={"value": HOST, "note": "uc-049 fake bank"})
    gw.post("/v1/egress/ranges", json={"value": bank.range, "note": "uc-049 fake bank network"})
    module_id = published_module(gw)
    policy = data(gw.get(f"/v1/tools/{WRITE}", headers=service_headers("tools")))["approval"]
    check("tools-service answers the published policy: two approvers", policy.get("approvers") == 2, policy)

    time.sleep(31)  # agents-service keeps each tenant's tool list for 30 seconds
    agent = data(api.post("/v1/agents", json={"name": f"Freezer {RUN}", "role": "Freezes accounts"}, headers=TEAM))
    granted = data(api.patch(f"/v1/agents/{agent['id']}", json={"toolIds": [WRITE]}, headers=TEAM))
    api.post(
        f"/v1/agents/{agent['id']}/publish-requests",
        json={"version": granted["version"], "note": "uc-049"},
        headers=TEAM,
    )
    thread = data(api.post("/chat/threads", json={"agentId": agent["id"], "kbIds": []}, headers=TEAM))["id"]
    res = api.post(
        f"/chat/threads/{thread}/messages",
        json={"content": f"call {WRITE} {json.dumps({'accountId': ACCOUNT})}"},
        headers={**TEAM, "Accept": "text/event-stream"},
    )
    events = sse(res.text)
    widget = next(
        (e["widget"] for e in events if e.get("type") == "widget" and e["widget"]["kind"] == "approval"), None
    )
    check(
        "the write stops on an approval card that asks for a step-up",
        widget is not None and widget.get("stepUp") is True,
        widget or [e.get("type") for e in events],
    )
    url = f"/chat/threads/{thread}/messages/{events[0]['messageId']}/widgets/{(widget or {}).get('id')}/actions"

    first = api.post(url, json={"type": "approve", "stepUpToken": step_up(api, MAYA)}, headers={**TEAM, **MAYA})
    check(
        "after one approval the call waits for a second person and nothing reaches the bank",
        first.status_code == 200 and data(first)["state"] == "awaiting_second" and not holds(bank),
        (first.status_code, first.text[:200], len(holds(bank))),
    )
    again = api.post(url, json={"type": "approve", "stepUpToken": step_up(api, MAYA)}, headers={**TEAM, **MAYA})
    check(
        "the same person approving again does not count", again.status_code >= 400 and not holds(bank), again.text[:200]
    )
    second = api.post(url, json={"type": "approve", "stepUpToken": step_up(api, PRIYA)}, headers={**TEAM, **PRIYA})
    check(
        "a second, different person approves and the write runs once",
        second.status_code == 200 and data(second)["state"] == "approved" and len(holds(bank)) == 1,
        (second.status_code, second.text[:200], len(holds(bank))),
    )
    rows = data(gw.get("/v1/executions", params={"tool": WRITE}))["data"]
    check(
        "the gateway allowed it on a token naming two approvers",
        [(r["decision"], r["status"]) for r in rows] == [("allow", "ok")],
        rows,
    )

finish()
