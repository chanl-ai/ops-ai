"""What uses one of a run's attempts, through the worker on PostgreSQL, by failure mode: a claim that found the run's
lease busy used an attempt; a worker stopped mid-step (a shutdown or a deploy) used one and left its claim to lapse;
and a long tool call whose heartbeat hit one database blip stopped renewing, so another worker reclaimed the run as
lost while the call still ran."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.engine_host import ThreadLeases
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.leases import Leases
from ops_agents.store.tenancy import tenant_scope
from ops_engine.ports import ToolResult
from ops_engine.store import RunStore, Work
from ops_engine.worker import Worker

from .test_worker import CountingTools, start, worker


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def claim_of(w: Worker, run_id: str) -> Work | None:
    """`w`'s claim of the run's row; rows other tests left are claimed and dropped on the way, as test_worker does."""
    while (got := await w.queue.claim()) is not None:
        if got.run_id == run_id:
            return got
    return None


async def work_row(engine: AsyncEngine, tenant: str, run_id: str) -> dict[str, Any]:
    with tenant_scope(tenant):
        (row,) = await RunStore(EngineTransactions(engine)).work(run_id)
    return row


class HeldTools(CountingTools):
    """A tool call that runs until the test lets it end."""

    def __init__(self) -> None:
        super().__init__()
        self.started, self.go = asyncio.Event(), asyncio.Event()

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.started.set()
        await self.go.wait()
        return await super().call(operation, input, key, generation, token)


async def test_a_claim_that_finds_the_run_busy_uses_no_attempt(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    run_id = await start(engine, tenant, {"customerId": "C-1", "amount": 250})
    # Another pass holds the run's lease.
    await ThreadLeases(Leases(engine, owner="other", ttl=30.0)).acquire(run_id, "holder")
    w = worker(engine, CountingTools(), InMemorySaver())
    claimed = await claim_of(w, run_id)
    assert claimed is not None
    await w.process(claimed)
    row = await work_row(engine, tenant, run_id)
    assert (row["status"], row["attempts"]) == ("queued", 0), row


async def test_a_worker_stopped_mid_step_gives_its_claim_back_without_an_attempt(engine: AsyncEngine) -> None:
    tenant, tools = f"t-{uuid4().hex[:8]}", HeldTools()
    run_id = await start(engine, tenant, {"customerId": "C-1", "amount": 250})
    w = worker(engine, tools, InMemorySaver())
    claimed = await claim_of(w, run_id)
    assert claimed is not None
    passing = asyncio.create_task(w.process(claimed))
    await asyncio.wait_for(tools.started.wait(), 10)
    passing.cancel()  # what run_forever does to each pass when the worker stops
    await asyncio.gather(passing, return_exceptions=True)
    row = await work_row(engine, tenant, run_id)
    assert (row["status"], row["attempts"], row["lapses"]) == ("queued", 0, 0), row


class BlippingLeases(ThreadLeases):
    """The lease's first renewal hits a database blip; every later one goes through."""

    def __init__(self, leases: Leases) -> None:
        super().__init__(leases)
        self.blipped = False

    async def heartbeat(self, thread_id: str, run_id: str) -> bool:
        if not self.blipped:
            self.blipped = True
            raise ConnectionError("database restarting")
        return await super().heartbeat(thread_id, run_id)


async def test_a_long_call_keeps_its_claim_through_a_heartbeat_blip(engine: AsyncEngine) -> None:
    tenant, tools = f"t-{uuid4().hex[:8]}", HeldTools()
    run_id = await start(engine, tenant, {"customerId": "C-1", "amount": 250})
    w = worker(engine, tools, InMemorySaver(), ttl=1.5)
    w.host.leases = BlippingLeases(Leases(engine, owner=w.host.owner, ttl=1.5))
    w.queue.ttl = 1.5
    claimed = await claim_of(w, run_id)
    assert claimed is not None
    passing = asyncio.create_task(w.process(claimed))
    await asyncio.wait_for(tools.started.wait(), 10)
    await asyncio.sleep(3.0)  # twice the claim's ttl, the call still running
    other = worker(engine, CountingTools(), InMemorySaver())
    taken = await claim_of(other, run_id)
    tools.go.set()
    (ended,) = await asyncio.gather(passing, return_exceptions=True)
    assert taken is None, "another worker reclaimed the run while its call was still running"
    assert ended is None and (await work_row(engine, tenant, run_id))["status"] == "done", ended
