"""uc-020 chat with the workflows, api layer: docs/usecases/agents-service/chat-starts-a-workflow.md."""

from __future__ import annotations

import re

from usecase_harness import TEAM, agents, check, data, finish, sse

ASK = "Start workflow dispute_email: I was charged twice for order 4411 and want the second charge reversed."


def chat(api, message: str) -> tuple[dict, list[dict]]:  # type: ignore[no-untyped-def]
    thread = data(api.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []}, headers=TEAM))
    res = api.post(
        f"/chat/threads/{thread['id']}/messages",
        json={"content": message},
        headers={**TEAM, "Accept": "text/event-stream"},
    )
    return thread, sse(res.text)


def children(api) -> list[str]:  # type: ignore[no-untyped-def]
    rows = data(api.get("/runs", params={"view": "open", "page": 1, "pageSize": 100}))["data"]
    return [
        r["id"]
        for r in rows
        if r["workflowId"] == "dispute_email" and (r.get("trigger") or "").startswith("Started by agent")
    ]


with agents() as api:
    # Non-vacuous first half: with the workflow paused, the agent is not offered it and no child starts.
    paused = api.post("/v1/workflows/dispute_email/status", json={"status": "paused"}, headers=TEAM)
    check("workflow paused (200)", paused.status_code == 200, paused.text[:200])
    before = children(api)
    _, events = chat(api, ASK)
    check(
        "a paused workflow is not called",
        not any(e["type"] == "tool_start" for e in events),
        [e["type"] for e in events],
    )
    check("and no child thread starts", children(api) == before, children(api))
    live = api.post("/v1/workflows/dispute_email/status", json={"status": "live"}, headers=TEAM)
    check("workflow live again (200)", live.status_code == 200, live.text[:200])

    thread, events = chat(api, ASK)
    started = next((e["call"] for e in events if e["type"] == "tool_start"), {})
    check("the agent calls the workflow as a tool", started.get("name") == "workflow__dispute_email", started)
    reply = events[-1].get("message", {}).get("content", "")
    child = re.search(r"gth_\w+", reply)
    check("the reply hands back the child's review", "waiting for a review" in reply and child is not None, reply)
    child_id = child.group(0) if child else ""
    row = next(
        (
            r
            for r in data(api.get("/runs", params={"view": "needs_person", "page": 1, "pageSize": 100}))["data"]
            if r["id"] == child_id
        ),
        None,
    )
    check(
        "the paused child is a Cases row started by the agent",
        row is not None and row["trigger"].startswith("Started by agent"),
        row,
    )

    decided = api.post(f"/reviews/{child_id}/decision", json={"decision": "approved"}, headers=TEAM)
    check("its review is decided in Reviews (200)", decided.status_code == 200, decided.text[:200])
    messages = data(api.get(f"/chat/threads/{thread['id']}", headers=TEAM))["messages"]
    last = messages[-1]["content"] if messages else ""
    check("the conversation shows the child's outcome", child_id in last and "finished" in last, last)

finish()
