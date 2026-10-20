"""The hot workflow and agent queries seek an index on their filters (c-280), by failure mode: every worker poll scans
the work queue for lapsed leases; every service event and the mailbox listener read every version of every workflow
to find the live ones; a team's thread list and event poll read every tenant's rows of the same team id; the runs list
filtered by one workflow reads the whole team. Each test records the SQL the store runs on a seeded crowd (ANALYZEd as
the table's owner) and asks PostgreSQL for its plan with sequential scans priced out; the plan has to seek the index
with the filtered columns in its Index Cond, so a scan of another index under a filter fails."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import uuid4

import asyncpg  # pyright: ignore[reportMissingTypeStubs]
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.events import EventLog, thread_events
from ops_agents.store.graphs import GraphStore, graph_threads
from ops_agents.store.service_events import listeners
from ops_agents.store.tenancy import current_tenant, tenant_scope, tenant_tx
from ops_checkpointer.saver import AsyncpgSaver, asyncpg_dsn
from ops_engine.store import DefinitionStore, RunStore, WorkQueue
from ops_engine.store.tables import ENGINE_BUILD, engine_definitions, engine_runs, engine_work
from ops_store import isolation
from tests.engine.test_runs_list_indexes import plans
from tests.engine.test_worker import engine  # noqa: F401  # pyright: ignore[reportUnusedImport]

AT = "2026-10-19T00:00:00+00:00"


def seeks(index: str, *columns: str) -> Callable[[str], bool]:
    """A plan that seeks `index` with each of `columns` in one Index Cond."""
    cond = r"\n\s*Index Cond: " + "".join(rf"(?=.*{c})" for c in columns)
    found = re.compile(re.escape(index) + r".*" + cond)
    return lambda plan: bool(found.search(plan))


@pytest.fixture
async def recorded(engine: AsyncEngine) -> AsyncIterator[list[tuple[str, Any]]]:  # noqa: F811
    """Every SELECT the engine sends, with its parameters."""
    seen: list[tuple[str, Any]] = []

    def record(_conn: Any, _cursor: Any, statement: str, parameters: Any, _context: Any, _many: bool) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    yield seen
    event.remove(engine.sync_engine, "before_cursor_execute", record)


async def analyse(engine: AsyncEngine, table: str) -> None:  # noqa: F811
    # As the table's owner: the tenant role may not analyse it, and PostgreSQL skips the request with only a warning.
    async with engine.begin() as c:
        await c.exec_driver_sql(f"ANALYZE {table}")


def about(statements: list[tuple[str, Any]], table: str) -> list[tuple[str, Any]]:
    return [s for s in statements if f"FROM {table}" in s[0]]


async def test_a_claim_seeks_both_due_work_and_lapsed_leases(
    engine: AsyncEngine,  # noqa: F811
    recorded: list[tuple[str, Any]],
) -> None:
    """300 finished rows and a few queued and claimed ones: the claim's two branches each seek their own index."""
    tx = EngineTransactions(engine)
    with tenant_scope(f"t_{uuid4().hex[:8]}"):
        rows: list[dict[str, Any]] = [
            {
                "tenant_id": tx.tenant(),
                "run_id": f"wfrun_{i}",
                "kind": "start",
                "dedupe_key": f"k{uuid4().hex}",
                "status": "done" if i % 50 else ("claimed" if i % 100 else "queued"),
                "build": ENGINE_BUILD,
                "available_at": 1e12,
                "lease_expires_at": 1e12 if i % 50 == 0 else None,
                "attempts": 1,
                "created_at": AT,
            }
            for i in range(300)
        ]
        async with tx.tenant_tx() as c:
            await c.execute(engine_work.insert(), rows)
        await analyse(engine, "engine_work")
        recorded.clear()
        await WorkQueue(tx, owner="plan", ttl=5).claim()
        [plan] = await plans(tx, [s for s in about(recorded, "engine_work") if "FOR UPDATE" in s[0]], bitmaps=True)
    assert seeks("ix_engine_work_lease", "status", "build", "lease_expires_at")(plan), plan
    assert seeks("ix_engine_work_due", "status", "build", "available_at")(plan), plan


async def test_listeners_and_the_mailbox_listener_read_live_versions_through_the_live_index(
    engine: AsyncEngine,  # noqa: F811
    recorded: list[tuple[str, Any]],
) -> None:
    """A workflow with 300 superseded versions and one live: both reads seek the live versions only."""
    tx = EngineTransactions(engine)
    with tenant_scope(f"t_{uuid4().hex[:8]}"):
        wid = f"wf_{uuid4().hex[:6]}"
        rows: list[dict[str, Any]] = [
            {
                "tenant_id": tx.tenant(),
                "workflow_id": wid if i % 3 else f"other_{i}",
                "version": i + 1,
                "digest": uuid4().hex,
                "name": "n",
                "definition": {},
                "created_at": AT,
                "created_by": "a@x",
                "stage": "live" if i == 299 else "superseded",
            }
            for i in range(300)
        ]
        async with tx.tenant_tx() as c:
            await c.execute(engine_definitions.insert(), rows)
        await analyse(engine, "engine_definitions")
        recorded.clear()
        await listeners(engine, "file.deleted", wid)
        await DefinitionStore(tx).live_everywhere()
        listened, everywhere = await plans(tx, about(recorded, "engine_definitions"))
    assert seeks("ix_engine_definitions_live", "tenant_id", "workflow_id")(listened), listened
    assert "ix_engine_definitions_live" in everywhere, everywhere


async def test_a_teams_thread_list_and_event_poll_lead_with_the_tenant_and_team(
    engine: AsyncEngine,  # noqa: F811
    recorded: list[tuple[str, Any]],
) -> None:
    """3000 threads and events over thirty teams: the list and the poll each seek tenant and team. Fewer rows, laid
    down in order, make a scan of the tenant index and a sort cheaper than the seek, which a year of data never is."""
    with tenant_scope(f"t_{uuid4().hex[:8]}"):
        threads: list[dict[str, Any]] = [
            {
                "id": f"th_{uuid4().hex[:12]}",
                "graph": "chat",
                "meta": {},
                "team_id": f"team_{i % 30}",
                "created_at": AT,
                "updated_at": f"2026-10-19T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}+00:00",
                "status": "idle",
            }
            for i in range(3000)
        ]
        events: list[dict[str, Any]] = [
            {
                "id": f"ev_{uuid4().hex[:12]}",
                "thread_id": t["id"],
                "seq": 1,
                "type": "started",
                "at": AT,
                "team_id": t["team_id"],
            }
            for t in threads
        ]
        async with tenant_tx(engine) as c:
            await c.execute(graph_threads.insert(), threads)
            await c.execute(thread_events.insert(), events)
        await analyse(engine, "graph_threads")
        await analyse(engine, "thread_events")
        with isolation.scope(current_tenant(), "team_1"):
            recorded.clear()
            await GraphStore(engine).threads(None)
            await EventLog(engine).team_events("team_1", 0)
        [listed] = await plans(EngineTransactions(engine), about(recorded, "graph_threads"))
        [polled] = await plans(EngineTransactions(engine), about(recorded, "thread_events"))
    assert seeks("ix_graph_threads_team_updated", "tenant_id", "team_id")(listed), listed
    assert seeks("ix_thread_events_tenant_team_position", "tenant_id", "team_id", "position")(polled), polled


async def test_the_runs_list_filtered_by_one_workflow_seeks_tenant_and_workflow(
    engine: AsyncEngine,  # noqa: F811
    recorded: list[tuple[str, Any]],
) -> None:
    """One team's 300 runs, ten of them of the workflow asked for: the page and its count seek the workflow."""
    tx = EngineTransactions(engine)
    with tenant_scope(f"t_{uuid4().hex[:8]}"):
        rows: list[dict[str, Any]] = [
            {
                "id": f"wfrun_{uuid4().hex[:12]}",
                "tenant_id": tx.tenant(),
                "team_id": "team_a",
                "workflow_id": "wf_one" if i % 30 == 0 else f"wf_{i % 7}",
                "version": 1,
                "digest": "d",
                "run_key": f"k{i}",
                "mode": "live",
                "status": "succeeded",
                "created_by": "b@x",
                "created_at": f"2026-10-19T00:{i // 60:02d}:{i % 60:02d}+00:00",
                "updated_at": AT,
            }
            for i in range(300)
        ]
        async with tx.tenant_tx() as c:
            await c.execute(engine_runs.insert(), rows)
        await analyse(engine, "engine_runs")
        recorded.clear()
        await RunStore(tx).page(workflow_id="wf_one", team_id="team_a")
        page, count = (await plans(tx, about(recorded, "engine_runs")))[:2]
    assert seeks("ix_engine_runs_workflow_created", "tenant_id", "workflow_id")(page), page
    assert seeks("ix_engine_runs_workflow_created", "tenant_id", "workflow_id")(count), count


async def connect(dsn: str) -> Any:
    """An asyncpg connection, typed as Any: asyncpg ships no type information."""
    return await asyncpg.connect(dsn)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


async def one_connection_pool(dsn: str) -> Any:
    return await asyncpg.create_pool(dsn, min_size=1, max_size=1)  # pyright: ignore[reportUnknownMemberType]


class Recording:
    """A pool whose connections record what the saver executes, so the test explains the saver's own statement."""

    def __init__(self, pool: Any) -> None:
        self.pool, self.seen = pool, cast(list[tuple[str, tuple[Any, ...]]], [])

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[Any]:
        async with self.pool.acquire() as conn:
            yield Recorded(conn, self.seen)

    async def close(self) -> None:
        await self.pool.close()


class Recorded:
    def __init__(self, conn: Any, seen: list[tuple[str, tuple[Any, ...]]]) -> None:
        self.conn, self.seen = conn, seen

    async def execute(self, query: str, *args: Any) -> str:
        self.seen.append((query, args))
        return await self.conn.execute(query, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.conn, name)


async def test_deleting_a_runs_checkpoints_seeks_the_run_id_in_their_metadata(engine: AsyncEngine) -> None:  # noqa: F811
    """3000 checkpoints of 300 runs in one tenant and team: deleting two runs' checkpoints seeks the run id."""
    tenant, team = f"t_{uuid4().hex[:8]}", "team_ops"
    dsn = asyncpg_dsn(engine.url.render_as_string(hide_password=False))
    conn = await connect(dsn)
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
            await conn.executemany(
                "INSERT INTO ops_checkpoints (tenant_id, team_id, thread_id, checkpoint_id, type, checkpoint, "
                "metadata_type, metadata_blob, metadata) VALUES ($1, $2, $3, $4, 'msgpack', '', 'json', '', $5::jsonb)",
                [(tenant, team, f"th_{i % 300}", f"cp_{i}", f'{{"run_id": "run_{i % 300}"}}') for i in range(3000)],
            )
        await conn.execute("ANALYZE ops_checkpoints")
        pool = Recording(await one_connection_pool(dsn))
        try:
            await AsyncpgSaver(pool, tenant_id=tenant, team_id=team).adelete_for_runs(["run_1", "run_2"])
        finally:
            await pool.close()
        [(statement, args)] = [s for s in pool.seen if "DELETE FROM ops_checkpoints" in s[0]]
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
            await conn.execute("SET LOCAL enable_seqscan = off")
            plan = "\n".join(r[0] for r in await conn.fetch(f"EXPLAIN {statement}", *args))
    finally:
        await conn.close()
    assert seeks("ix_ops_checkpoints_run", "tenant_id", "team_id", "run_id")(plan), plan
