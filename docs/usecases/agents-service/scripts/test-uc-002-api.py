"""uc-002 write tool pauses, approval resumes with step-up, api layer: docs/usecases/agents-service/write-tool-approval-step-up.md."""

from __future__ import annotations

from usecase_harness import TEAM, agents, check, data, finish, sse

with agents() as api:
    thread = data(api.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_people"]}, headers=TEAM))
    res = api.post(
        f"/chat/threads/{thread['id']}/messages",
        json={"content": "Place a 24-hour hold on wire W-88213"},
        headers={**TEAM, "Accept": "text/event-stream"},
    )
    events = sse(res.text)
    widget = next((e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval"), None)
    check("write tool paused on an approval widget", widget is not None, [e["type"] for e in events])
    assert widget is not None
    check("widget is pending and asks for a step-up", widget["state"] == "pending" and widget["stepUp"] is True, widget)
    gated = next((e["call"] for e in events if e["type"] == "tool_end"), {})
    check("call routed to Fraud Operations", gated.get("gated", {}).get("reviewers") == "Fraud Operations", gated)

    url = f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"
    # Non-vacuous: the same approve without a step-up token must be refused, so a pass below proves the token counted.
    refused = api.post(url, json={"type": "approve"}, headers=TEAM)
    check(
        "approve without step-up is refused (422)",
        refused.status_code == 422 and "step-up" in refused.json()["error"]["message"],
        refused.text[:200],
    )
    fake = api.post(url, json={"type": "approve", "stepUpToken": "stepup_test"}, headers=TEAM)
    check("approve with an unsigned step-up is refused (422)", fake.status_code == 422, fake.text[:200])
    minted = api.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers=TEAM)
    check("step-up minted by re-authenticating (200)", minted.status_code == 200, minted.text[:200])
    token = data(minted)["token"]
    approved = api.post(url, json={"type": "approve", "stepUpToken": token}, headers=TEAM)
    check(
        "approve with step-up succeeds",
        approved.status_code == 200 and data(approved)["state"] == "approved",
        approved.text[:200],
    )
    again = api.post(url, json={"type": "approve", "stepUpToken": token}, headers=TEAM)
    check("a second decision is refused (409)", again.status_code == 409, again.status_code)

    messages = data(api.get(f"/chat/threads/{thread['id']}", headers=TEAM))["messages"]
    last = messages[-1]
    check("run resumed and the hold is in place", "hold is in place" in last["content"], last["content"])
    call = (last.get("toolCalls") or [{}])[0]
    check(
        "tool ran once with a reference",
        call.get("status") == "success" and str(call.get("output", {}).get("reference", "")).startswith("NB-"),
        call,
    )

finish()
