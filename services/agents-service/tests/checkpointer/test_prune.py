"""prune_thread drops a thread's step history only once the thread is closed and its run is in the journal."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.base.id import uuid6
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.graphs import graph_runs, graph_threads
from ops_agents.store.journal import GraphJournal
from ops_checkpointer import RLS_ROLE, AsyncpgSaver, Pool

pytestmark = pytest.mark.usefixtures("local_tenant")


@pytest.fixture
async def engine(database_url: str) -> Any:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def _history(saver: AsyncpgSaver, thread_id: str, steps: int) -> None:
    config: Any = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    for step in range(steps):
        cp = empty_checkpoint()
        cp["id"] = str(uuid6(clock_seq=step))
        config = await saver.aput(config, cp, {"source": "loop", "step": step}, {})
        await saver.aput_writes(config, [("messages", f"m{step}")], task_id=f"task-{step}")


async def _count(saver: AsyncpgSaver, thread_id: str) -> int:
    return len([t async for t in saver.alist({"configurable": {"thread_id": thread_id}})])


async def test_prune_waits_for_closed_thread_and_journal_row(pool: Pool, engine: AsyncEngine) -> None:
    saver = AsyncpgSaver(pool, tenant_id=f"p-{uuid4().hex}", team_id="team", role=RLS_ROLE)
    journal = GraphJournal(engine)
    thread_id, run_id, now = f"gth-{uuid4().hex[:12]}", f"run-{uuid4().hex[:12]}", "2026-10-10T00:00:00Z"
    await _history(saver, thread_id, 3)
    async with engine.begin() as c:
        await c.execute(
            graph_threads.insert().values(
                id=thread_id,
                graph="simple_workflow",
                meta={},
                team_id="team",
                created_at=now,
                updated_at=now,
                status="busy",
            )
        )
        await c.execute(
            graph_runs.insert().values(
                id=run_id, thread_id=thread_id, kind="run", status="running", events=[], created_at=now
            )
        )

    assert not await saver.prune_thread(thread_id, journal)  # running: no journal row yet
    assert await _count(saver, thread_id) == 3

    async with engine.begin() as c:
        await c.execute(
            graph_runs.update().where(graph_runs.c.id == run_id).values(status="interrupted", finished_at=now)
        )
        await c.execute(graph_threads.update().where(graph_threads.c.id == thread_id).values(status="interrupted"))
    assert not await saver.prune_thread(thread_id, journal)  # paused on a person: resume needs the history
    assert await _count(saver, thread_id) == 3

    async with engine.begin() as c:
        await c.execute(graph_threads.update().where(graph_threads.c.id == thread_id).values(status="idle"))
    assert await saver.prune_thread(thread_id, journal)
    kept = [t async for t in saver.alist({"configurable": {"thread_id": thread_id}})]
    assert len(kept) == 1
    assert kept[0].metadata.get("step") == 2
    assert [w[2] for w in kept[0].pending_writes or []] == ["m2"]
