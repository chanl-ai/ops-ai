"""The stack's seeded agents (seed/chat_agents.json, c-048 G1), by failure mode: the registry seeded from the fixture
agents although the setting names the stack's file, and a seeded agent granted a tool tools-service's dev seed does
not hold, which the agent would silently never get."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_service_kit.settings import Settings
from tests.conftest import ROOT, SEED, FakeGraphModels, fixture_knowledge, scripted_model

STACK_AGENTS = ROOT / "seed" / "chat_agents.json"
TOOLS_SEED = ROOT.parent / "tools-service" / "seed" / "tool_modules.json"


@pytest.fixture
async def stack_client() -> AsyncIterator[AsyncClient]:
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, agents_seed_file=STACK_AGENTS)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(
        settings,
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


async def test_the_registry_is_seeded_from_the_configured_agents_file(stack_client: AsyncClient) -> None:
    expected = {a["id"]: a["tools"] for a in json.loads(STACK_AGENTS.read_text())}
    for agent_id, tools in expected.items():
        r = await stack_client.get(f"/v1/agents/{agent_id}")
        assert r.status_code == 200, r.text
        assert r.json()["data"]["toolIds"] == tools


def test_every_seeded_grant_is_an_operation_tools_service_seeds() -> None:
    seeded_ops = {o["name"] for m in json.loads(TOOLS_SEED.read_text())["modules"] for o in m["operations"]}
    for agent in json.loads(STACK_AGENTS.read_text()):
        grants = [t for t in agent["tools"] if not t.startswith("workflow:")]
        # An agent that answers from knowledge alone (ag_policy) holds no grant; one that holds any must hold
        # operations the registry offers at start, never a fixture tool or one an import adds later.
        assert set(grants) <= seeded_ops, (agent["id"], set(grants) - seeded_ops)
