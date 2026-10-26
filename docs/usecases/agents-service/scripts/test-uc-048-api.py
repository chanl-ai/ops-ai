"""uc-048 an agent is granted and calls a published tools-service operation, api layer:
docs/usecases/agents-service/agent-calls-registry-operations.md. agents-service runs with tools-service as its gateway
and the scripted model; the operations call the fake bank on https, so "the call ran" is checked on the bank's side."""

from __future__ import annotations

import json
import time
from typing import Any

from fake_bank_https import HOST, fake_bank
from usecase_harness import AGENTS_PORT, TEAM, TOOLS_PORT, agents, approve_tool_review, check, data, finish, sse, tools

SECURITY = {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}
RUN = int(time.time())
READ, WRITE = f"get_balance_{RUN}", f"hold_account_{RUN}"
ACCOUNT = "CHQ-2219"


def module(gw: Any) -> tuple[str, str]:
    """A draft module with one read and one write on the fake bank; returns its id and pending review id."""
    url = f"https://{HOST}/v1"
    name = f"harborpine-{RUN}"
    made = data(
        gw.post("/v1/tool-modules/blank", json={"displayName": f"Harbor & Pine {RUN}", "name": name, "type": "http"})
    )
    for op in (
        {
            "name": READ,
            "description": "Balance of a chequing account",
            "access": "read",
            "method": "GET",
            "url": f"{url}/accounts/{{accountId}}",
        },
        {
            "name": WRITE,
            "description": "Place a hold on an account",
            "access": "write",
            "method": "POST",
            "url": f"{url}/accounts/{{accountId}}/holds",
        },
    ):
        gw.post(f"/v1/tool-modules/{made['id']}/operations", json=op)
    reviewed = data(gw.post(f"/v1/tool-modules/{made['id']}/reviews", json={"note": "uc-048"}))
    return str(made["id"]), next(v["reviewId"] for v in reviewed["versions"] if v["status"] == "in_review")


def offered(api: Any) -> dict[str, dict[str, Any]]:
    return {t["id"]: t for t in data(api.get("/v1/tools", headers=TEAM))}


def chat(api: Any, thread: str, content: str) -> list[dict[str, Any]]:
    res = api.post(
        f"/chat/threads/{thread}/messages", json={"content": content}, headers={**TEAM, "Accept": "text/event-stream"}
    )
    return sse(res.text)


def widgets(node: Any) -> list[dict[str, Any]]:
    """Every approval widget anywhere in a stream event."""
    if isinstance(node, dict):
        found = [node] if "reviewId" in node and "fields" in node else []
        return found + [w for v in node.values() for w in widgets(v)]
    if isinstance(node, list):
        return [w for v in node for w in widgets(v)]
    return []


settings = {"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}
with (
    fake_bank() as bank,
    agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}") as api,
    tools(settings={**bank.settings, **settings}) as gw,
):
    gw.post("/v1/egress/hosts", json={"value": HOST, "note": "uc-048 fake bank"})
    gw.post("/v1/egress/ranges", json={"value": bank.range, "note": "uc-048 fake bank network"})
    module_id, review = module(gw)

    before = offered(api)
    check("an operation of a module still in review is not offered to agents", READ not in before, sorted(before))
    check(
        "a fixture-only tool is not offered: agents grant from the registry",
        "lookup_account" not in before,
        sorted(before),
    )

    approve_tool_review(gw, module_id, SECURITY)
    time.sleep(31)  # agents-service keeps each tenant's list for 30 seconds
    after = offered(api)
    read = after.get(READ) or {}
    check(
        "once published, the operation is offered with its module, access and input schema",
        read.get("server") == f"Harbor & Pine {RUN}"
        and read.get("access") == "read"
        and (read.get("inputSchema") or {}).get("required") == ["accountId"],
        read,
    )
    check(
        "the write is offered as needing approval",
        (after.get(WRITE) or {}).get("requiresApproval") is True,
        after.get(WRITE),
    )

    agent = data(
        api.post("/v1/agents", json={"name": f"Account Checker {RUN}", "role": "Checks accounts"}, headers=TEAM)
    )
    aid = agent["id"]
    refused = api.patch(f"/v1/agents/{aid}", json={"toolIds": ["lookup_account"]}, headers=TEAM)
    check(
        "granting a tool the registry does not offer is refused (400 unknown_tool)",
        refused.status_code == 400 and refused.json()["error"]["code"] == "unknown_tool",
        refused.text[:200],
    )
    granted = api.patch(f"/v1/agents/{aid}", json={"toolIds": [READ, WRITE]}, headers=TEAM)
    check("granting the published operations is accepted", granted.status_code == 200, granted.text[:200])
    published = api.post(
        f"/v1/agents/{aid}/publish-requests", json={"version": data(granted)["version"], "note": "uc-048"}, headers=TEAM
    )
    check("the agent is published", published.status_code == 201, published.text[:200])

    thread = data(api.post("/chat/threads", json={"agentId": aid, "kbIds": []}, headers=TEAM))["id"]
    events = chat(api, thread, f"call {READ} {json.dumps({'accountId': ACCOUNT})}")
    started = [e["call"]["name"] for e in events if e.get("type") == "tool_start"]
    text = "".join(e.get("delta", "") for e in events if e.get("type") == "text")
    reads = [r for r in bank.received if r["method"] == "GET" and r["path"] == f"/v1/accounts/{ACCOUNT}"]
    check(
        "a chat turn calls the read and the fake bank receives it",
        started == [READ] and "found" in text and len(reads) == 1,
        {"events": [e.get("type") for e in events], "started": started, "received": len(reads)},
    )
    # c-055 T004: the bank's answer is one flat object, so it streams as a record part and is kept on reload.
    parts = [e["part"] for e in events if e.get("type") == "part"]
    kept = [p for m in data(api.get(f"/chat/threads/{thread}", headers=TEAM))["messages"] for p in m.get("parts") or []]
    check(
        "the read's answer streams as a record part, kept on reload, naming no tool",
        len(parts) == 1 and parts[0]["shape"] == "record" and kept == parts and READ not in json.dumps(parts),
        {"parts": parts, "kept": kept},
    )
    logged = data(gw.get("/v1/executions", params={"tool": READ}))["data"]
    check(
        "tools-service logged the call as allowed and ok, made by the agent",
        [(r["decision"], r["status"], r["actor"]) for r in logged]
        == [("allow", "ok", {"kind": "agent", "id": aid, "name": aid})],
        logged,
    )

    events = chat(api, thread, f"call {WRITE} {json.dumps({'accountId': ACCOUNT})}")
    holds = [r for r in bank.received if r["method"] == "POST"]
    cards = [w for e in events for w in widgets(e) if w.get("tool") == WRITE]
    check(
        "the approval card shows the input the call will send",
        bool(cards) and cards[-1].get("fields") == [{"label": "accountId", "value": ACCOUNT}],
        cards or [e.get("type") for e in events],
    )
    check(
        "the write stops for approval and nothing reaches the bank",
        not holds and any("approval" in json.dumps(e) for e in events),
        {"events": [e.get("type") for e in events], "posts": len(holds)},
    )

finish()
