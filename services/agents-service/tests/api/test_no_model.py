"""Started with no model key: health says degraded with the reason, the registry still lists and reads (a database
read needs no model), and a write that needs a model answers 503 model_unavailable, never 500."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.graphs import metadata
from ops_service_kit.settings import Settings

from ..conftest import SEED
from ..contract import response_checker


@pytest.fixture
async def keyless() -> AsyncGenerator[AsyncClient]:
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, openai_api_key=None, anthropic_api_key=None)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(settings, engine=engine)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t", event_hooks={"response": [response_checker(app)]}
        ) as c,
    ):
        yield c


async def test_health_is_degraded_and_says_why(keyless: AsyncClient) -> None:
    r = await keyless.get("/health")
    assert r.status_code == 503, r.text
    assert "OPENAI_API_KEY" in r.json()["error"]["message"]


async def test_the_registry_reads_without_a_model(keyless: AsyncClient) -> None:
    agents = await keyless.get("/v1/agents")
    assert agents.status_code == 200 and agents.json()["data"]["pagination"]["total"] == 3, agents.text
    assert (await keyless.get("/v1/agents/ag_fraud")).status_code == 200
    workflows = await keyless.get("/v1/workflows")
    assert workflows.status_code == 200 and workflows.json()["data"]["pagination"]["total"] == 2, workflows.text
    assert (await keyless.get("/v1/workflows/dispute_email")).status_code == 200
    graphs = await keyless.get("/v1/graphs")
    assert graphs.status_code == 200 and "dispute_email" in {g["name"] for g in graphs.json()["data"]}, graphs.text


async def test_writes_that_need_a_model_answer_503(keyless: AsyncClient) -> None:
    turn = await keyless.post("/v1/agents/ag_fraud/test", json={"message": "hi"})
    run = await keyless.post("/v1/workflows/dispute_email/test", json={})
    for r in (turn, run):
        assert r.status_code == 503 and r.json()["error"]["code"] == "model_unavailable", r.text
