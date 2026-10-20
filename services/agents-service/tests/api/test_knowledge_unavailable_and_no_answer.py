"""Knowledge refused and no-answer (c-056 T005 review, T014), by failure mode: a stack with no kb-service answering
from somewhere else and looking healthy, a knowledge-free agent unusable without a kb-service, and every reply that
found no passage drawn as the not-found note (a plain or tool answer included)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.activities.catalog import AgentDefinition
from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_service_kit.contract import response_checker
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, scripted_model, sse_events


@pytest.fixture
async def no_kb() -> AsyncIterator[tuple[AsyncClient, Any]]:
    """agents-service with no kb-service configured and no stand-in injected."""
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(
        settings, model=scripted_model(), engine=engine, checkpointer=InMemorySaver(), graph_models=FakeGraphModels()
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", event_hooks={"response": [response_checker(app)]}
        ) as client,
    ):
        yield client, app.state.runtime


async def say(client: AsyncClient, thread_id: str, content: str) -> list[dict[str, Any]]:
    r = await client.post(
        f"/chat/threads/{thread_id}/messages", json={"content": content}, headers={"Accept": "text/event-stream"}
    )
    assert r.status_code == 200, r.text
    return sse_events(r.text)


async def test_without_a_kb_service_knowledge_is_refused_as_unavailable(no_kb: tuple[AsyncClient, Any]) -> None:
    client, _ = no_kb
    named = await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_people"]})
    assert named.status_code == 503 and named.json()["error"]["code"] == "knowledge_unavailable", named.text
    granted = await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []})
    assert granted.status_code == 503, "an agent that holds knowledge bases needs the knowledge service"


async def test_a_knowledge_free_agent_works_without_a_kb_service(no_kb: tuple[AsyncClient, Any]) -> None:
    client, rt = no_kb
    plain = rt.catalog.agent("ag_branch")
    rt.catalog.put_agent(AgentDefinition.model_validate({**plain.model_dump(), "id": "ag_plain", "default_kb_ids": []}))
    created = await client.post("/chat/threads", json={"agentId": "ag_plain", "kbIds": []})
    assert created.status_code == 201, created.text
    events = await say(client, created.json()["data"]["id"], "Hello there")
    assert events[-1]["type"] == "done" and not events[-1]["message"].get("noAnswer"), events[-1]


async def test_no_answer_only_when_the_conversation_asked_for_knowledge(client: AsyncClient) -> None:
    """`client` carries the fixture knowledge. A thread that names no knowledge base and gets a plain reply is not a
    no-answer; a thread that names one and asks what none of it covers is."""
    plain = (await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []})).json()["data"]
    events = await say(client, plain["id"], "Hello there")
    assert events[-1]["message"].get("noAnswer") is not True, events[-1]
    stored = (await client.get(f"/chat/threads/{plain['id']}")).json()["data"]["messages"][-1]
    assert stored.get("noAnswer") is not True
    asked = (await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": ["kb_people"]})).json()["data"]
    events = await say(client, asked["id"], "What is on the staff canteen menu today?")
    assert events[-1]["message"].get("noAnswer") is True, events[-1]
