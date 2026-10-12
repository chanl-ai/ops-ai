"""Pausing an agent, by failure mode: a conversation cut mid-turn (an approval decided after the pause fails), and
new messages or conversations accepted, or refused without saying why."""

from __future__ import annotations

from httpx import AsyncClient

from tests.api.test_chat import new_thread, send
from tests.conftest import step_up

WIRE = "Place a 24-hour hold on wire W-88213"


async def pause(client: AsyncClient, agent_id: str, paused: bool = True) -> None:
    res = await client.post(f"/v1/agents/{agent_id}/paused", json={"paused": paused})
    assert res.status_code == 200, res.text


async def test_a_paused_agent_refuses_new_messages_and_conversations_with_the_reason(client: AsyncClient) -> None:
    thread = await new_thread(client)
    await send(client, thread["id"], {"content": "What is the daily wire limit for a personal account?"})
    await pause(client, "ag_fraud")
    more = await client.post(f"/chat/threads/{thread['id']}/messages", json={"content": "And for business?"})
    assert more.status_code == 409 and more.json()["error"]["code"] == "agent_paused"
    assert "paused" in more.json()["error"]["message"]
    fresh = await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_people"]})
    assert fresh.status_code == 409 and fresh.json()["error"]["code"] == "agent_paused"
    await pause(client, "ag_fraud", paused=False)
    _, events = await send(client, thread["id"], {"content": "And for business?"})
    assert events[-1]["type"] == "done"


async def test_a_turn_under_way_finishes_after_the_pause(client: AsyncClient) -> None:
    thread = await new_thread(client)
    _, events = await send(client, thread["id"], {"content": WIRE})
    widget = next(e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval")
    await pause(client, "ag_fraud")
    url = f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"
    approved = await client.post(url, json={"type": "approve", "stepUpToken": await step_up(client)})
    assert approved.status_code == 200, approved.text
    reply = (await client.get(f"/chat/threads/{thread['id']}")).json()["data"]["messages"][-1]
    assert "hold is in place" in reply["content"] and not reply.get("error")
