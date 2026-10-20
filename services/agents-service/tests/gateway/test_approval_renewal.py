"""An approval token that expires between the decision and the call, by failure mode: the late resume refused for
good although its approvals stand, and an old approval renewed forever."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.graphs import metadata
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, decide, fixture_knowledge, last_run, scripted_model
from tests.gateway.conftest import Gateway
from tests.gateway.test_dispute_e2e import paused_dispute


async def app_with(gateway: Gateway, **settings: Any) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(
        Settings(
            database_url="sqlite+aiosqlite://",
            seed_dir=SEED,
            review_key=SecretStr("test-review-key"),
            review_token_ttl_seconds=1,
            **settings,
        ),
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        gateway=gateway.client,
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as c,
    ):
        yield c, app


async def decided_then_expired(client: httpx.AsyncClient, app: FastAPI) -> str:
    """A decision whose resume found the thread busy, retried after its token's TTL."""
    tid, _ = await paused_dispute(client)
    leases = app.state.runtime.leases
    await leases.acquire(tid, "run_busy")
    busy = await client.post(f"/reviews/{tid}/decision", json={"decision": "approved"})
    assert busy.status_code == 409, busy.text
    await asyncio.sleep(1.5)  # past the 1-second token TTL
    await leases.release(tid, "run_busy")
    await decide(client, tid)
    return tid


@pytest.fixture
async def renewing(gateway: Gateway) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    async for pair in app_with(gateway):
        yield pair


@pytest.fixture
async def strict(gateway: Gateway) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    async for pair in app_with(gateway, approval_renewal_max_age_seconds=0):
        yield pair


async def test_a_late_resume_renews_the_token_from_the_recorded_approvals(
    renewing: tuple[httpx.AsyncClient, FastAPI], gateway: Gateway
) -> None:
    client, app = renewing
    tid = await decided_then_expired(client, app)
    assert (await last_run(client, tid))["status"] == "done"
    rows = await gateway.log.for_thread(tid, tenant_id="local")
    # The expired token was refused once, then the renewed one sent the reply exactly once.
    assert [(r["decision"], r["outcome"]) for r in rows] == [("deny", "refused"), ("allow", "ok")]


async def test_an_approval_older_than_the_renewal_age_needs_a_fresh_review(
    strict: tuple[httpx.AsyncClient, FastAPI], gateway: Gateway
) -> None:
    client, app = strict
    tid = await decided_then_expired(client, app)
    assert (await last_run(client, tid))["status"] == "error"
    assert [(r["decision"], r["outcome"]) for r in await gateway.log.for_thread(tid, tenant_id="local")] == [
        ("deny", "refused")
    ]
