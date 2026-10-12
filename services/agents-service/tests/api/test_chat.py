"""API failure modes against the console's contract: envelope or field names drifting from chat.ts, frames the
console's SSE reader cannot split, a money approval without step-up getting through, a decision applied twice,
and regenerate leaving the old reply in the thread."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from tests.conftest import sse_events, step_up


async def new_thread(
    client: AsyncClient, agent_id: str = "ag_fraud", kb_ids: list[str] | None = None
) -> dict[str, Any]:
    res = await client.post("/chat/threads", json={"agentId": agent_id, "kbIds": kb_ids or ["kb_people"]})
    assert res.status_code == 201, res.text
    return res.json()["data"]


async def send(client: AsyncClient, thread_id: str, body: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    res = await client.post(f"/chat/threads/{thread_id}/messages", json=body, headers={"Accept": "text/event-stream"})
    assert res.status_code == 200, res.text
    return res.text, sse_events(res.text)


async def test_envelope_and_list_shape_match_console(client: AsyncClient) -> None:
    agents = (await client.get("/chat/agents")).json()
    assert agents["success"] is True
    assert {"id", "name", "role", "version", "model", "defaultKbIds", "suggestions"} <= set(agents["data"][0])
    fraud = next(a for a in agents["data"] if a["id"] == "ag_fraud")
    assert fraud["kbs"] == [{"id": "kb_people", "name": "Fraud & payments"}, {"id": "kb_eng", "name": "Compliance"}]
    thread = await new_thread(client)
    assert thread["kbNames"] == ["Fraud & payments"] and thread["messages"] == []
    widened = await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_support"]})
    assert widened.status_code == 422 and "Retail banking" in widened.json()["error"]["message"]
    listed = (await client.get("/chat/threads?page=1&pageSize=10&agentId=ag_fraud")).json()["data"]
    assert listed["pagination"] == {
        "page": 1,
        "pageSize": 10,
        "total": 1,
        "totalPages": 1,
        "hasNext": False,
        "hasPrev": False,
    }
    assert listed["facets"]["agentId"] == {"ag_fraud": 1}
    assert {"preview", "widgets", "citations", "messageCount"} <= set(listed["data"][0])
    missing = await client.get("/chat/threads/th_nope")
    assert missing.status_code == 404
    assert missing.json()["success"] is False and missing.json()["error"]["message"]


async def test_reply_streams_console_frames_and_is_stored(client: AsyncClient) -> None:
    thread = await new_thread(client)
    raw, events = await send(client, thread["id"], {"content": "What is the daily wire limit for a personal account?"})
    assert "\r\n" not in raw
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "done"
    assert "text" in types and "citations" in types
    citations = next(e for e in events if e["type"] == "citations")["citations"]
    assert citations[0]["documentId"] == "doc_wire_limits" and citations[0]["n"] == 1
    stored = (await client.get(f"/chat/threads/{thread['id']}")).json()["data"]
    assert [m["role"] for m in stored["messages"]] == ["user", "assistant"]
    assert stored["messages"][1]["id"] == events[0]["messageId"]
    assert stored["messages"][1]["citations"][0]["documentId"] == "doc_wire_limits"
    assert stored["messages"][1]["model"] == "function:scripted:scripted_stream"
    assert stored["title"].startswith("What is the daily wire limit")


async def test_money_approval_needs_step_up_then_continues(client: AsyncClient) -> None:
    thread = await new_thread(client)
    _, events = await send(client, thread["id"], {"content": "Place a 24-hour hold on wire W-88213"})
    widget = next(e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval")
    assert widget["state"] == "pending" and widget["fields"][0] == {"label": "Wire", "value": "W-88213"}
    assert widget["movesMoney"] is True
    gated = next(e["call"] for e in events if e["type"] == "tool_end")
    assert gated["gated"]["reviewers"] == "Fraud Operations"
    mid = events[0]["messageId"]
    url = f"/chat/threads/{thread['id']}/messages/{mid}/widgets/{widget['id']}/actions"

    refused = await client.post(url, json={"type": "approve"})
    assert refused.status_code == 422
    assert "step-up" in refused.json()["error"]["message"]

    token = await step_up(client)
    approved = await client.post(url, json={"type": "approve", "stepUpToken": token})
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["state"] == "approved"

    again = await client.post(url, json={"type": "approve", "stepUpToken": token})
    assert again.status_code == 409

    messages = (await client.get(f"/chat/threads/{thread['id']}")).json()["data"]["messages"]
    continuation = messages[-1]
    assert continuation["role"] == "assistant" and "hold is in place" in continuation["content"]
    assert continuation["toolCalls"][0]["status"] == "success"
    assert continuation["toolCalls"][0]["output"]["reference"].startswith("NB-")


async def test_regenerate_replaces_the_reply(client: AsyncClient) -> None:
    thread = await new_thread(client)
    _, first = await send(client, thread["id"], {"content": "What is the daily wire limit for a personal account?"})
    old = first[0]["messageId"]
    _, second = await send(client, thread["id"], {"content": "", "regenerate": old})
    messages = (await client.get(f"/chat/threads/{thread['id']}")).json()["data"]["messages"]
    assert [m["id"] for m in messages if m["role"] == "assistant"] == [second[0]["messageId"]]
    assert len([m for m in messages if m["role"] == "user"]) == 1
