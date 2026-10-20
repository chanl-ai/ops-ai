"""Chat on the graph path, by failure mode: a conversation that is not a graph thread, a message sent around the
thread's lease, a reload that differs from what streamed, feedback that does not survive a reload, an approval
decided outside Reviews, and a new message slipping past a pending approval."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.store.graphs import metadata
from ops_agents.store.reviews import review_decisions
from ops_service_kit.settings import Settings
from tests.api.test_chat import new_thread, send
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model, step_up

QUESTION = "What is the daily wire limit for a personal account?"
WIRE = "Place a 24-hour hold on wire W-88213"


@pytest.fixture
async def stack() -> AsyncIterator[tuple[AsyncClient, Runtime]]:
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
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client, cast(Runtime, app.state.runtime)


async def stored(client: AsyncClient, tid: str) -> dict[str, Any]:
    return (await client.get(f"/chat/threads/{tid}")).json()["data"]


async def test_a_conversation_is_a_graph_thread_and_a_message_is_a_run(stack: tuple[AsyncClient, Runtime]) -> None:
    client, _ = stack
    thread = await new_thread(client)
    await send(client, thread["id"], {"content": QUESTION})
    listed = (await client.get("/v1/threads", params={"graph": "agent_wrapper"})).json()["data"]
    assert thread["id"] in [t["threadId"] for t in listed]
    runs = (await client.get(f"/v1/threads/{thread['id']}/runs")).json()["data"]
    assert [r["kind"] for r in runs] == ["input"] and runs[0]["status"] == "done"


async def test_a_message_waits_for_the_threads_lease(stack: tuple[AsyncClient, Runtime]) -> None:
    client, rt = stack
    thread = await new_thread(client)
    assert rt.leases is not None
    await rt.leases.acquire(thread["id"], "run_elsewhere")
    res = await client.post(f"/chat/threads/{thread['id']}/messages", json={"content": QUESTION})
    assert res.status_code == 409 and res.json()["error"]["code"] == "run_active"


async def test_a_reload_shows_what_streamed(stack: tuple[AsyncClient, Runtime]) -> None:
    client, _ = stack
    thread = await new_thread(client)
    _, events = await send(client, thread["id"], {"content": QUESTION})
    done = events[-1]["message"]
    reloaded = (await stored(client, thread["id"]))["messages"][-1]
    for key in ("id", "content", "citations", "model"):
        assert reloaded[key] == done[key], key


async def test_feedback_survives_a_reload_and_can_be_cleared(stack: tuple[AsyncClient, Runtime]) -> None:
    client, _ = stack
    thread = await new_thread(client)
    _, events = await send(client, thread["id"], {"content": QUESTION})
    url = f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/feedback"
    assert (await client.put(url, json={"feedback": {"rating": "down", "reason": "Too long"}})).status_code == 200
    assert (await stored(client, thread["id"]))["messages"][-1]["feedback"] == {"rating": "down", "reason": "Too long"}
    assert (await client.put(url, json={"feedback": None})).status_code == 200
    assert (await stored(client, thread["id"]))["messages"][-1].get("feedback") is None


async def test_an_approval_is_decided_in_reviews_and_blocks_new_messages_until_then(
    stack: tuple[AsyncClient, Runtime],
) -> None:
    client, rt = stack
    thread = await new_thread(client)
    _, events = await send(client, thread["id"], {"content": WIRE})
    widget = next(e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval")
    blocked = await client.post(f"/chat/threads/{thread['id']}/messages", json={"content": QUESTION})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "run_waiting"
    url = f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"
    approved = await client.post(url, json={"type": "approve", "stepUpToken": await step_up(client)})
    assert approved.status_code == 200 and approved.json()["data"]["state"] == "approved"
    assert rt.graph_store is not None
    async with rt.graph_store.engine.connect() as c:
        decided = (await c.execute(sa.select(review_decisions.c.decision, review_decisions.c.resumed_at))).all()
    assert len(decided) == 1 and decided[0].decision == "approved" and decided[0].resumed_at is not None
    roles = [m["role"] for m in (await stored(client, thread["id"]))["messages"]]
    assert roles == ["user", "assistant", "assistant"]  # the resumed run's reply is the continuation
