# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-949 a new workspace writes without waiting, api layer: docs/usecases/platform-service/a-new-workspace-chats-and-writes.md,
steps 1, 2, 5 and 6. Own services, no real model: platform-service seeds a new workspace (its first-run policies),
tools-service reads the team's approval rules from it, and agents-service runs on the scripted model with tools-service
as its gateway. send_reply is a write its seed declares ask-first, so a wait here would be the maker's."""

from __future__ import annotations

import json
import time

from usecase_harness import (
    TOOLS_PORT,
    agents,
    bearer,
    check,
    data,
    finish,
    platform,
    save_agent,
    service_headers,
    signed_in,
    sse,
    tools,
)

TEAM = {"X-Team-Id": "team_ops"}
RUN = int(time.time())
WRITE = "send_reply"


def answer() -> dict[str, object]:
    """The gateway's answer for the write in the team, as agents-service reads it to offer and run the tool."""
    headers = service_headers("tools", scopes=["tools:view"], team="team_ops") | TEAM
    rows = data(gw.get("/v1/grantable-operations", headers=headers)) or []
    return next((r for r in rows if r.get("name") == WRITE), {"missing": [r.get("name") for r in rows][:20]})


with (
    platform() as (people, _),
    tools(approval_rules=True) as gw,
    agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}") as api,
):
    priya = bearer(signed_in(people, "p.shah@harborpine.example"), "team_ops")
    # Steps 1 and 2: a new workspace starts with publish review never, any public address, makers' asks and step-up off.
    held = {k: data(people.get(f"/v1/policies/{k}", headers=priya))["value"] for k in ("publishReview", "egressNewHosts", "appChanges", "stepUp")}  # fmt: skip
    first = next(iter((held["publishReview"] or {}).values()), {})
    check("1 publish review is never and new addresses are any_public", bool(first) and set(first.values()) == {"never"} and held["egressNewHosts"] == "any_public", held)  # fmt: skip
    check("2 makers' ask-first writes and step-up are off", (held["appChanges"] or {}).get("*", {}).get("makersAsk") is False and held["stepUp"] is False, held)  # fmt: skip

    said = answer()
    check("5 the gateway answers that the maker's ask-first write does not wait", said.get("requiresApproval") is False and said.get("answer") == "none", said)

    # Step 5: an agent with the write calls it in chat, and it runs with no approval card.
    agent = data(api.post("/v1/agents", json={"name": f"Replier {RUN}", "role": "Replies to customers"}, headers=TEAM))
    granted = data(save_agent(api, agent["id"], {"toolIds": [WRITE]}, headers=TEAM))
    api.post(f"/v1/agents/{agent['id']}/publish-requests", json={"version": granted["version"], "note": "uc-949"}, headers=TEAM)  # fmt: skip
    thread = data(api.post("/chat/threads", json={"agentId": agent["id"], "kbIds": []}, headers=TEAM))["id"]
    args = {"to": "r.alvarez@example.com", "subject": "Your request", "body": "We received it."}
    res = api.post(
        f"/chat/threads/{thread}/messages",
        json={"content": f"call {WRITE} {json.dumps(args)}"},
        headers={**TEAM, "Accept": "text/event-stream"},
        timeout=120,
    )
    events = sse(res.text)
    widgets = [e["widget"]["kind"] for e in events if e.get("type") == "widget"]
    ended = next((e["call"] for e in events if e.get("type") == "tool_end"), {})
    check("5 the write runs at once: no approval card, the call succeeds", "approval" not in widgets and ended.get("status") == "success", (widgets, ended))  # fmt: skip
    rows = data(gw.get("/v1/executions", params={"tool": WRITE}))["data"]
    check("5 the gateway ran it once", [(r["decision"], r["status"]) for r in rows] == [("allow", "ok")], rows)

    # Step 6: a team that turns makers' asks back on waits again, so the answer above came from the new workspace's value.
    on = people.put("/v1/policies/appChanges", json={"value": {"makersAsk": True}}, headers=priya)
    check("6 the team admin turns makers' asks on", on.status_code == 200, on.text[:200])
    said = answer()
    check("6 the same write now waits for a reviewer", said.get("requiresApproval") is True and said.get("answer") == "reviewer", said)  # fmt: skip

finish()
