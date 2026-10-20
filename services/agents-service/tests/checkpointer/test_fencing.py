"""E2b fencing at the checkpointer, on the compose PostgreSQL: a stalled owner's checkpoint write after a takeover is
refused, a write with no generation on a fenced thread is refused, and heartbeats keep the generation (and the
owner's writes) stable. The saver keeps its own fence table and never reads the Runtime's leases."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.graphs import GraphStore
from ops_agents.store.leases import Leases, db_now, thread_leases
from ops_checkpointer import LeaseSupersededError, open_saver
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.settings import Settings

pytestmark = pytest.mark.usefixtures("local_tenant")

DATABASE_URL = Settings().database_url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    # `database_url` (tests/checkpointer/conftest.py) has migrated the database once per session.
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


def cfg(thread: str, generation: int | None) -> Any:
    configurable: dict[str, Any] = {"thread_id": thread, "checkpoint_ns": ""}
    if generation is not None:
        configurable["lease_generation"] = generation
    return {"configurable": configurable}


async def put(saver: Any, thread: str, generation: int | None) -> None:
    await saver.aput(cfg(thread, generation), empty_checkpoint(), {"source": "loop", "step": 0, "parents": {}}, {})


async def expire(engine: AsyncEngine, thread: str) -> None:
    async with engine.begin() as c:
        await c.execute(
            thread_leases.update().where(thread_leases.c.thread_id == thread).values(expires_at=db_now(engine) - 1)
        )


async def test_stalled_owner_cannot_checkpoint_after_takeover(engine: AsyncEngine) -> None:
    thread = new_id("fence")
    a, b = Leases(engine, "proc-a", ttl=30), Leases(engine, "proc-b", ttl=30)
    gen_a = await a.acquire(thread, "run_a")
    await expire(engine, thread)  # A is stalled past its TTL
    gen_b = await b.acquire(thread, "run_b")
    assert gen_b == gen_a + 1
    async with open_saver(DATABASE_URL, tenant_id="t", team_id="t") as saver:
        await put(saver, thread, gen_b)
        with pytest.raises(LeaseSupersededError):
            await put(saver, thread, gen_a)
        with pytest.raises(LeaseSupersededError):
            stale = cfg(thread, gen_a)
            stale["configurable"]["checkpoint_id"] = "x"
            await saver.aput_writes(stale, [("ch", 1)], "task")


async def test_fenced_thread_refuses_unfenced_writes(engine: AsyncEngine) -> None:
    thread = new_id("fence")
    gen = await Leases(engine, "proc-a", ttl=30).acquire(thread, "run_a")
    async with open_saver(DATABASE_URL, tenant_id="t", team_id="t") as saver:
        await saver.araise_fence(thread, gen)  # the owner raises the fence before it reads the thread
        with pytest.raises(LeaseSupersededError):
            await put(saver, thread, None)
        await put(saver, new_id("unfenced"), None)  # a thread no owner ever fenced is not checked


async def test_heartbeat_keeps_generation_and_writes(engine: AsyncEngine) -> None:
    thread = new_id("fence")
    leases = Leases(engine, "proc-a", ttl=30)
    gen = await leases.acquire(thread, "run_a")
    for _ in range(3):
        assert await leases.heartbeat(thread, "run_a")
    assert await leases.generation_of(thread, "run_a") == gen
    async with open_saver(DATABASE_URL, tenant_id="t", team_id="t") as saver:
        await put(saver, thread, gen)
    await leases.release(thread, "run_a")
    assert await Leases(engine, "proc-b", ttl=30).acquire(thread, "run_b") == gen + 1  # the count survives release


async def test_same_process_retaking_its_thread_refuses_its_old_generation(engine: AsyncEngine) -> None:
    """The fence is per thread, not per worker: one process that pauses, loses its lease and takes the thread back
    under a new run must not let the paused run's writes through, checkpoint or journal (ADR-0016)."""
    thread, run_old, run_new = new_id("fence"), new_id("run"), new_id("run")
    leases = Leases(engine, "proc-a", ttl=30)
    store = GraphStore(engine)
    await store.create_thread(thread, "complex_workflow", {}, "team", now_iso())
    old = await leases.acquire(thread, run_old)
    assert await store.start_run(run_old, thread, "input", now_iso(), generation=old)
    await expire(engine, thread)  # the same process stalls past its TTL
    new = await leases.acquire(thread, run_new)
    assert new == old + 1
    async with open_saver(DATABASE_URL, tenant_id="t", team_id="t") as saver:
        await saver.araise_fence(thread, new)
        with pytest.raises(LeaseSupersededError):
            await put(saver, thread, old)
    with pytest.raises(LeaseSupersededError):
        await store.set_thread_status(thread, "idle", now_iso(), generation=old)
    await store.finish_run(run_old, "done", [{"event": "end"}], now_iso(), generation=old)
    row = await store.run(run_old)
    assert row is not None and row["status"] == "running"  # the stale finish did not overwrite the record
    assert row["events"][-1]["event"] == "stale_owner_finished"
