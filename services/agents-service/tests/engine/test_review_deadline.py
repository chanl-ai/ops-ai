"""A review step's deadline on the real worker (c-074), on PostgreSQL: a step set to expire leaves on its timeout port
once its deadline passes, and a person who decides first wins. By failure mode: nothing ever expires the step; a
timeout queued for a review the person already decided resumes the run a second time."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api import engine_reviews
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import DefinitionStore, RunStore
from ops_service_kit.ids import new_id
from tests.engine.test_worker import CountingTools, M, drain, worker

# About a second and a half: long enough to decide inside it, short enough to wait out.
SLA_HOURS = 1.5 / 3600

FLOW = parse(
    {
        "schemaVersion": 2,
        "id": "deadline_check",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {
                "id": "review",
                "type": "ops.flow.humanReview",
                "typeVersion": 1,
                "parameters": {"title": "Check it", "slaHours": SLA_HOURS, "onTimeout": "expire"},
            },
            {"id": "ok", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "approved"}},
            {"id": "no", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "rejected"}},
            {"id": "late", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "expired"}},
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "review", "port": "in"}},
            {"from": {"node": "review", "port": "approve"}, "to": {"node": "ok", "port": "in"}},
            {"from": {"node": "review", "port": "reject"}, "to": {"node": "no", "port": "in"}},
            {"from": {"node": "review", "port": "timeout"}, "to": {"node": "late", "port": "in"}},
        ],
    }
)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def start(engine: AsyncEngine, tenant: str) -> str:
    tx = EngineTransactions(engine)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            FLOW.id, name="Deadline", definition=FLOW.wire(), digest=FLOW.digest(), now="now", by="a@x", stage="live"
        )
        run_id = new_id("wfrun")
        await RunStore(tx).create(
            {
                "id": run_id,
                "team_id": "team_a",
                "workflow_id": FLOW.id,
                "version": version,
                "digest": FLOW.digest(),
                "run_key": run_id,
                "mode": "live",
                "input": {},
                "created_by": "a@x",
            }
        )
        return run_id


async def ended(engine: AsyncEngine, tenant: str, run_id: str) -> dict[str, Any]:
    with tenant_scope(tenant):
        return await RunStore(EngineTransactions(engine)).get(run_id) or {}


async def test_a_review_past_its_deadline_leaves_on_timeout(engine: AsyncEngine) -> None:
    tenant, saver = f"t-{uuid4().hex[:8]}", InMemorySaver()
    run_id = await start(engine, tenant)
    w = worker(engine, CountingTools(), saver)
    await drain(w)
    assert (await ended(engine, tenant, run_id))["status"] == "waiting"
    await drain(w)
    assert (await ended(engine, tenant, run_id))["status"] == "waiting", "the timeout waits for its deadline"
    await asyncio.sleep(2)
    await drain(w)
    run = await ended(engine, tenant, run_id)
    assert (run["status"], run["outcome"]) == ("succeeded", "expired")


async def test_a_person_who_decides_first_wins_over_the_deadline(engine: AsyncEngine) -> None:
    tenant, saver = f"t-{uuid4().hex[:8]}", InMemorySaver()
    run_id = await start(engine, tenant)
    w = worker(engine, CountingTools(), saver)
    await drain(w)
    rt: Any = SimpleNamespace(db=engine, settings=SimpleNamespace(lease_ttl_seconds=6.0))
    with tenant_scope(tenant):
        await engine_reviews.decide(rt, M, run_id, decision="approved", reason=None)
    await drain(w)
    await asyncio.sleep(2)
    await drain(w)
    run = await ended(engine, tenant, run_id)
    assert (run["status"], run["outcome"]) == ("succeeded", "approved")
