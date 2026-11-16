"""Lists whose sort column holds equal values order those rows by id, so a page never repeats or skips one: the
workflow threads and runs lists and the engine runs list. Rows are written with one timestamp, out of id
order, so a list that leaves ties to the database answers them in the order they were written."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.graphs import GraphStore
from ops_engine.store import RunStore
from ops_engine.store.tables import engine_runs
from ops_store import isolation

AT = "2026-11-16T00:00:00+00:00"
TEAM = "team_ops"
# Neither in id order nor its reverse, so a list read forward or backward through an index still shows the tie.
IDS = ["a", "c", "b"]


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def _threads(e: AsyncEngine, tag: str) -> list[str]:
    store = GraphStore(e)
    for i in IDS:
        await store.create_thread(f"th_{tag}_{i}", f"g_{tag}", {}, TEAM, AT)
    return [t["id"] for t in await store.threads(f"g_{tag}")]


async def _graph_runs(e: AsyncEngine, tag: str) -> list[str]:
    store = GraphStore(e)
    await store.create_thread(f"th_{tag}", f"g_{tag}", {}, TEAM, AT)
    for i in IDS:
        await store.start_run(f"gr_{tag}_{i}", f"th_{tag}", "invoke", AT)
    listed = [r["id"] for r in await store.runs(f"th_{tag}")]
    summaries = await store.run_summaries(f"th_{tag}")
    assert len(summaries[f"th_{tag}"]) == len(IDS)
    return listed


async def _engine_runs(e: AsyncEngine, tag: str) -> list[str]:
    tx = EngineTransactions(e)
    rows: list[dict[str, Any]] = [
        {
            "id": f"wfrun_{tag}_{i}",
            "tenant_id": tx.tenant(),
            "team_id": TEAM,
            "workflow_id": f"wf_{tag}",
            "version": 1,
            "digest": "d",
            "run_key": f"k_{tag}_{i}",
            "mode": "live",
            "status": "succeeded",
            "created_by": "a@x",
            "created_at": AT,
            "updated_at": AT,
        }
        for i in IDS
    ]
    async with tx.tenant_tx() as c:
        await c.execute(engine_runs.insert(), rows)
    return [r["id"] for r in await RunStore(tx).list(workflow_id=f"wf_{tag}")]


@pytest.mark.parametrize(
    ("listing", "prefix"),
    [(_threads, "th_{tag}_"), (_graph_runs, "gr_{tag}_"), (_engine_runs, "wfrun_{tag}_")],
)
async def test_rows_with_one_sort_value_are_listed_by_id(
    engine: AsyncEngine,
    listing: Callable[[AsyncEngine, str], Awaitable[list[str]]],
    prefix: str,
) -> None:
    tag = uuid4().hex[:8]
    with isolation.scope(f"t_{tag}", TEAM):
        listed = await listing(engine, tag)
    assert listed == [prefix.format(tag=tag) + i for i in sorted(IDS)]
