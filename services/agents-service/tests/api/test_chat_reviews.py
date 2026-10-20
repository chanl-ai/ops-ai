"""A chat's write approval in Reviews (c-048 T013, G24), by failure mode: a chat hold missing from the list so the
second approver needs a chat link, a row that cannot say where it came from, and a decision in Reviews that does not
resume the conversation."""

from __future__ import annotations

from typing import Any, cast

from httpx import AsyncClient

from tests.conftest import sse_events

ASKER, APPROVER = {"X-Dev-User": "dana@northfieldbank.com"}, {"X-Dev-User": "lee@northfieldbank.com"}
WRITE = 'call request_document {"customerId": "C-1042", "document": "proof of address", "reason": "Moved"}'


async def _hold(client: AsyncClient) -> str:
    res = await client.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []}, headers=ASKER)
    thread = str(res.json()["data"]["id"])
    sent = await client.post(
        f"/chat/threads/{thread}/messages", json={"content": WRITE}, headers={**ASKER, "Accept": "text/event-stream"}
    )
    assert any(e["type"] == "widget" for e in sse_events(sent.text)), "the write stops for approval"
    return thread


async def test_a_chat_write_approval_is_listed_in_reviews_with_where_it_came_from(client: AsyncClient) -> None:
    thread = await _hold(client)
    rows = (await client.get("/reviews", params={"view": "open"})).json()["data"]["data"]
    row = next((r for r in rows if r["id"] == thread), None)
    assert row is not None, [r["id"] for r in rows]
    assert row["origin"] == {"kind": "chat", "threadId": thread, "agentName": "Card Dispute Resolver"}
    assert row["title"] == "Run request_document for Card Dispute Resolver"
    assert row["status"] == "pending"


async def test_approving_it_in_reviews_resumes_the_conversation(client: AsyncClient) -> None:
    thread = await _hold(client)
    decided = await client.post(f"/reviews/{thread}/decision", json={"decision": "approved"}, headers=APPROVER)
    assert decided.status_code == 200, decided.text
    assert decided.json()["data"]["status"] == "approved"
    messages: list[dict[str, Any]] = (await client.get(f"/chat/threads/{thread}", headers=ASKER)).json()["data"][
        "messages"
    ]
    assert messages[-1]["role"] == "assistant" and messages[-1]["content"], "the agent answered after the approval"
    calls: list[dict[str, Any]] = [
        c
        for m in messages
        for c in cast(list[dict[str, Any]], m.get("toolCalls") or [])
        if c["name"] == "request_document"
    ]
    assert calls and calls[-1]["status"] == "success", calls
