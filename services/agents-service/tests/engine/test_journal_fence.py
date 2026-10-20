"""The step journal is fenced like every other write of a run: a worker whose lease was taken over cannot record a
step, so its stale output can never become the step's recorded one."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.leases import Leases
from ops_agents.store.tenancy import tenant_scope
from ops_checkpointer import LeaseSupersededError
from ops_engine.journal import StepRow
from ops_engine.store import SqlJournal


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_a_superseded_worker_cannot_record_a_step(engine: AsyncEngine) -> None:
    run = f"wfrun_{uuid4().hex[:10]}"
    old = await Leases(engine, owner="a", ttl=0.2).acquire(run, "a")
    with tenant_scope(f"t-{uuid4().hex[:6]}"):
        journal = SqlJournal(EngineTransactions(engine))
        first = StepRow(run, "lookup", 1, 1, "running", "read", f"{run}:lookup:1:1", generation=old)
        await journal.begin(first)  # A starts attempt 1, then stalls past its lease
        await asyncio.sleep(0.4)
        new = await Leases(engine, owner="b", ttl=6.0).acquire(run, "b")
        second = StepRow(run, "lookup", 1, 2, "running", "read", f"{run}:lookup:1:2", generation=new)
        await journal.begin(second)
        await journal.finish(second, status="ok", port="ok", output={"by": "b"}, error=None)
        with pytest.raises(LeaseSupersededError):
            await journal.finish(first, status="ok", port="ok", output={"by": "a"}, error=None)
        with pytest.raises(LeaseSupersededError):
            await journal.begin(StepRow(run, "next", 1, 1, "running", "none", f"{run}:next:1:1", generation=old))
        rows = await journal.steps(run, "lookup", 1)
    assert [(r.attempt, r.status, r.output) for r in rows] == [(1, "running", None), (2, "ok", {"by": "b"})]
