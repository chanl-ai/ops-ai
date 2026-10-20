"""A chat turn stopped by the step limit (c-058 T003 follow-up), on the stream and in the stored message: the reply
says it was cut short rather than ending on its partial text."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, looping_model, sse_events

NOTICE = "(Reply cut short: the agent reached its step limit for one reply.)"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(
        Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED),
        model=looping_model(text="The daily ATM limit is 1,000. "),
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


async def test_a_reply_cut_short_by_the_step_limit_says_so_on_the_stream_and_when_reloaded(client: AsyncClient) -> None:
    tid = (await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []})).json()["data"]["id"]
    res = await client.post(
        f"/chat/threads/{tid}/messages",
        json={"content": "What is the daily ATM limit?"},
        headers={"Accept": "text/event-stream"},
    )
    assert res.status_code == 200, res.text
    text = "".join(e.get("delta", "") for e in sse_events(res.text) if e.get("type") == "text")
    assert text.startswith("The daily ATM limit is 1,000.") and text.endswith(NOTICE), text
    saved = (await client.get(f"/chat/threads/{tid}")).json()["data"]["messages"][-1]
    assert saved["content"].endswith(NOTICE), saved["content"]
