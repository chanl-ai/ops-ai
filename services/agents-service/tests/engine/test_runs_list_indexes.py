"""The runs list reads engine_runs through an index (c-312), by failure mode: the list sorts every run the tenant has to
show one team's page, filtered or not, and a parent settling on its unfinished runs answers wrongly once it asks by
status. The list test records the SQL the store runs, then asks PostgreSQL for that statement's plan with sequential
scans priced out, so a plan that sorts the whole list or picks another index means no index serves the store's query.
An incremental sort on the presorted created_at only orders ties by id."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RunStore
from ops_engine.store.tables import engine_runs
from tests.engine.test_worker import engine  # noqa: F401  # pyright: ignore[reportUnusedImport]

FULL_SORT = re.compile(r"(?<!Incremental )Sort  \(")
# The parent index sought by parent and status, not scanned under a filter.
SEEK = re.compile(r"ix_engine_runs_parent_status.*\n\s*Index Cond: .*created_by.*status")


def parent_id() -> str:
    """A parent run id of this test's own. One id shared by every test and every run of the suite became one of the
    commonest values in created_by on a database that keeps its rows, and the planner then priced the parent index
    like any other; a fresh id is as rare as a real parent's."""
    return f"wfrun_{uuid4().hex[:12]}"


async def crowded(tx: EngineTransactions, parent: str) -> None:
    """The shape the indexes are for, with the table's statistics read: in team_a a parent's 100 finished runs, 100
    runs waiting on a person and 100 under way that other people started; in team_b as many under way. With few
    unfinished rows in the parent's own team, the team and status index is as cheap as the parent's, so the plan would
    not show which one the query needs."""
    kinds = [
        ("team_a", "succeeded", f"run:{parent}"),
        ("team_a", "running", "b@x"),
        ("team_a", "waiting", "b@x"),
        ("team_b", "running", "b@x"),
    ]
    at = "2026-10-19T00:00:00+00:00"
    rows = [
        {
            "id": f"wfrun_{uuid4().hex[:12]}",
            "tenant_id": tx.tenant(),
            "team_id": kinds[i % 4][0],
            "workflow_id": "wf",
            "version": 1,
            "digest": "d",
            "run_key": f"k{i}",
            "mode": "live",
            "status": kinds[i % 4][1],
            "created_by": kinds[i % 4][2],
            "created_at": f"2026-10-19T00:{i // 60:02d}:{i % 60:02d}+00:00",
            "updated_at": at,
        }
        for i in range(400)
    ]
    async with tx.tenant_tx() as c:
        await c.execute(engine_runs.insert(), rows)
    # As the table's owner: the tenant role may not analyse it, and PostgreSQL skips the request with only a warning.
    async with tx.engine.begin() as c:
        await c.exec_driver_sql("ANALYZE engine_runs")


@pytest.fixture
async def recorded(engine: AsyncEngine) -> AsyncIterator[list[tuple[str, Any]]]:  # noqa: F811
    """Every engine_runs SELECT the engine sends, with its parameters."""
    seen: list[tuple[str, Any]] = []

    def record(_conn: Any, _cursor: Any, statement: str, parameters: Any, _context: Any, _many: bool) -> None:
        if statement.lstrip().upper().startswith("SELECT") and "engine_runs" in statement:
            seen.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    yield seen
    event.remove(engine.sync_engine, "before_cursor_execute", record)


async def plans(tx: EngineTransactions, statements: list[tuple[str, Any]], *, bitmaps: bool = False) -> list[str]:
    out: list[str] = []
    async with tx.tenant_tx() as c:
        await c.exec_driver_sql("SET LOCAL enable_seqscan = off")
        # A bitmap scan and a sort cost less than an ordered index scan on a small table, which a fresh test database
        # has; ruled out too, the plan shows which index serves the filter and the order, not what is cheapest today.
        # A query whose OR needs two indexes together keeps them (`bitmaps`).
        if not bitmaps:
            await c.exec_driver_sql("SET LOCAL enable_bitmapscan = off")
        for statement, parameters in statements:
            rows = await c.exec_driver_sql(f"EXPLAIN {statement}", parameters)
            out.append("\n".join(str(r[0]) for r in rows))
    return out


async def test_one_teams_page_of_runs_reads_an_index_in_order_with_or_without_a_status(
    engine: AsyncEngine,  # noqa: F811
    recorded: list[tuple[str, Any]],
) -> None:
    tx = EngineTransactions(engine)
    parent = parent_id()
    with tenant_scope(f"t_{uuid4().hex[:8]}"):
        await crowded(tx, parent)
        recorded.clear()
        await RunStore(tx).page(team_id="team_a")
        await RunStore(tx).page(team_id="team_a", statuses=["waiting"])
        listed = [s for s in recorded if "ORDER BY" in s[0]]
        unfiltered, filtered = await plans(tx, listed)
    assert "ix_engine_runs_team_created" in unfiltered and not FULL_SORT.search(unfiltered), unfiltered
    assert "ix_engine_runs_team_status_created" in filtered and not FULL_SORT.search(filtered), filtered


async def test_a_parent_reads_running_or_waiting_from_its_unfinished_runs_among_hundreds_it_started(
    engine: AsyncEngine,  # noqa: F811
) -> None:
    tx = EngineTransactions(engine)
    store = RunStore(tx)
    parent = parent_id()
    with tenant_scope(f"t_{uuid4().hex[:8]}"):
        await crowded(tx, parent)
        mine = engine_runs.c.created_by == f"run:{parent}"
        answers: list[str | None] = []
        for status in (None, "queued", "waiting"):
            async with tx.tenant_tx() as c:
                if status:
                    one = sa.select(engine_runs.c.id).where(mine, engine_runs.c.status == "succeeded").limit(1)
                    pick = engine_runs.c.id == one.scalar_subquery()
                    await c.execute(engine_runs.update().where(pick).values(status=status))
                answers.append(await store._children_left(c, parent))  # pyright: ignore[reportPrivateUsage]
    assert answers == [None, "running", "waiting"]


async def test_a_run_ending_asks_its_parent_index_not_every_sibling(
    engine: AsyncEngine,  # noqa: F811
    recorded: list[tuple[str, Any]],
) -> None:
    """Each run that ends settles its parent with two EXISTS lookups. Both must seek ix_engine_runs_parent_status on
    the parent and status: a plan that only scans the index and filters reads the parent's runs on every child's end,
    so a parent of n runs costs n squared to finish."""
    tx = EngineTransactions(engine)
    parent = parent_id()
    with tenant_scope(f"t_{uuid4().hex[:8]}"):
        await crowded(tx, parent)
        recorded.clear()
        async with tx.tenant_tx() as c:
            await RunStore(tx)._children_left(c, parent)  # pyright: ignore[reportPrivateUsage]
        asked = await plans(tx, [s for s in recorded if "EXISTS" in s[0].upper()])
    assert len(asked) == 2 and all(SEEK.search(p) for p in asked), asked
