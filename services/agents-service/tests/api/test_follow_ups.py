"""Quick replies under a reply, by failure mode: the model's likely answers never reach the message, so the console has
no chips to draw; a reload loses them; and a long menu passes as replies."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(
        Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED),
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


async def ask(client: AsyncClient, replies: list[str]) -> dict[str, object]:
    tid = (await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []})).json()["data"]["id"]
    say = "call present " + json.dumps({"followUps": replies})
    res = await client.post(
        f"/chat/threads/{tid}/messages", json={"content": say}, headers={"Accept": "text/event-stream"}
    )
    assert res.status_code == 200, res.text
    return (await client.get(f"/chat/threads/{tid}")).json()["data"]["messages"][-1]


async def test_the_models_likely_answers_are_the_reply_follow_ups_after_a_reload(client: AsyncClient) -> None:
    reply = await ask(client, ["Update Education savings", "Open a new opportunity"])
    assert reply["followUps"] == ["Update Education savings", "Open a new opportunity"], reply


async def test_more_than_three_replies_are_refused(client: AsyncClient) -> None:
    reply = await ask(client, ["a", "b", "c", "d"])
    assert not reply.get("followUps"), reply


async def test_think_harder_reruns_the_last_reply_on_the_deeper_alias(client: AsyncClient) -> None:
    tid = (await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []})).json()["data"]["id"]
    headers = {"Accept": "text/event-stream"}
    await client.post(f"/chat/threads/{tid}/messages", json={"content": "Hello"}, headers=headers)
    first = (await client.get(f"/chat/threads/{tid}")).json()["data"]["messages"]
    res = await client.post(f"/chat/threads/{tid}/messages", json={"content": "Think harder"}, headers=headers)
    assert res.status_code == 200, res.text
    after = (await client.get(f"/chat/threads/{tid}")).json()["data"]["messages"]
    # The reply is answered again, not "Think harder" as a new question: one question, one (new) reply.
    assert [m["role"] for m in after] == ["user", "assistant"], after
    assert after[0]["content"] == "Hello" and after[1]["id"] != first[1]["id"]
    ran: dict[str, Any] = after[1].get("settings") or {}
    assert ran.get("model") == "thinking" and ran.get("sources", {}).get("model") == "think_harder", ran


async def test_asking_to_think_harder_in_a_sentence_answers_it_on_the_deeper_alias(client: AsyncClient) -> None:
    # "think harder - what should we do next?" ran on the everyday model and got a save read-back, not advice.
    tid = (await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []})).json()["data"]["id"]
    headers = {"Accept": "text/event-stream"}
    await client.post(f"/chat/threads/{tid}/messages", json={"content": "Hello"}, headers=headers)
    ask = "think harder - what should we do next?"
    res = await client.post(f"/chat/threads/{tid}/messages", json={"content": ask}, headers=headers)
    assert res.status_code == 200, res.text
    after = (await client.get(f"/chat/threads/{tid}")).json()["data"]["messages"]
    # A new question, kept as asked, answered on the deeper model; the earlier exchange stays.
    assert [m["content"] for m in after if m["role"] == "user"] == ["Hello", ask], after
    ran: dict[str, Any] = after[-1].get("settings") or {}
    assert ran.get("model") == "thinking" and ran.get("sources", {}).get("model") == "think_harder", ran


async def test_a_message_that_only_mentions_thinking_is_not_a_think_harder_ask(client: AsyncClient) -> None:
    tid = (await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []})).json()["data"]["id"]
    headers = {"Accept": "text/event-stream"}
    await client.post(
        f"/chat/threads/{tid}/messages", json={"content": "I think the hardware is fine"}, headers=headers
    )
    after = (await client.get(f"/chat/threads/{tid}")).json()["data"]["messages"]
    ran: dict[str, Any] = after[-1].get("settings") or {}
    assert ran.get("sources", {}).get("model") != "think_harder", after
