"""A v2 workflow called as an agent's tool: a run no worker picks up within the wait is reported as not done, never
as a success the model would read as finished."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api import child_runs
from ops_agents.api.app import create_app
from ops_agents.api.child_runs import ChildRuns
from ops_agents.api.deps import Runtime
from ops_agents.store.base import metadata
from ops_agents.store.tenancy import LOCAL_TENANT, tenant_scope
from ops_engine.store import metadata as engine_metadata
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model

BASIC = Path(__file__).parents[1] / "fixtures" / "engine" / "basic.yaml"


@pytest.fixture
async def stack() -> AsyncIterator[tuple[AsyncClient, Runtime]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
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


async def test_a_run_no_worker_finished_in_time_is_not_reported_as_done(
    stack: tuple[AsyncClient, Runtime], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, rt = stack
    assert (await client.post("/v1/workflows/definitions", json={"yaml": BASIC.read_text()})).status_code == 201
    # A saved version is a draft; dev auto-approve takes it live, as a reviewer's approval would.
    published = await client.post("/v1/workflows/definitions/refund_check/publish-requests", json={})
    assert published.status_code == 201 and published.json()["data"]["status"] == "approved", published.text
    parent = (await client.post("/v1/threads", json={"graph": "agent_wrapper", "metadata": {}})).json()["data"]
    monkeypatch.setattr(child_runs, "ENGINE_WAIT_SECONDS", 0.3)
    with tenant_scope(LOCAL_TENANT):
        outcome = await ChildRuns(rt).run(
            workflow="refund_check",
            arguments={"customerId": "C-1", "amount": 250},
            key="turn_1:call_1",
            parent_thread_id=parent["threadId"],
            parent_run_id=None,
        )
    assert outcome.ok is False, outcome.output
    assert outcome.output["status"] == "queued" and isinstance(outcome.output["runId"], str)
