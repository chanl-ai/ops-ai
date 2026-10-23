"""The database holds the run tables to the caller's team (c-429, migration 0073; workflow runs and cases, c-507, 0076),
with raw SQL and no WHERE clause as ops_runtime_tenant, by failure mode: a team transaction reading or writing another
team's thread, run, event, decision, approval, workflow run or case; a tenant-wide one reading another tenant's; and a
table whose generated policy is dropped, which must fail the suite naming it. On the PostgreSQL test database migrated
to head."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.cases import cases
from ops_agents.store.events import thread_events
from ops_agents.store.graphs import graph_runs, graph_threads
from ops_agents.store.reviews import review_approvals, review_decisions
from ops_agents.store.tenancy import TENANT_ROLE
from ops_engine.store.tables import engine_runs
from ops_service_kit.ids import new_id, now_iso
from ops_store.conformance import isolation_suite
from ops_store.schema import isolation_ddl

TABLES = (graph_threads, graph_runs, thread_events, review_decisions, review_approvals, engine_runs, cases)
PARENT = "gth_isolation_suite_parent"


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    async with e.begin() as c:  # the compose superuser, past the policy: a thread the runs can point at
        await c.execute(graph_threads.delete().where(graph_threads.c.id == PARENT))
        now = now_iso()
        await c.execute(
            graph_threads.insert().values(
                id=PARENT, graph="g", meta={}, team_id="t", created_at=now, updated_at=now, status="idle", tenant_id="x"
            )
        )
    yield e
    async with e.begin() as c:
        await c.execute(graph_threads.delete().where(graph_threads.c.id == PARENT))
    await e.dispose()


def _run(_tenant: str, _team: str | None) -> dict[str, Any]:
    return {"id": new_id("run"), "thread_id": PARENT, "kind": "input", "status": "done", "events": []}


FILL = {"graph_runs": _run}


async def test_each_run_table_holds_a_team_to_its_rows(engine: AsyncEngine) -> None:
    assert await isolation_suite(engine, TABLES, role=TENANT_ROLE, fill=FILL) == []


async def test_a_dropped_policy_fails_the_suite_naming_its_table(engine: AsyncEngine) -> None:
    async with engine.begin() as c:
        await c.execute(sa.text("DROP POLICY graph_runs_isolation ON graph_runs"))
    try:
        failures = await isolation_suite(engine, TABLES, role=TENANT_ROLE, fill=FILL)
    finally:
        async with engine.begin() as c:
            for statement in isolation_ddl(graph_runs, "postgresql"):
                await c.execute(sa.text(statement))
    assert failures and {f.split(":")[0] for f in failures} == {"graph_runs"}, failures
