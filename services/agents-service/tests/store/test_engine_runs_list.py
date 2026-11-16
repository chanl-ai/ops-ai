"""The engine runs list a page at a time in SQL (`RunStore.listed`), by failure mode: another team's run on the page or
in the status counts when the database lets every team through; the status counts narrowed by their own filter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.engine import EngineTransactions
from ops_engine.store import RunStore
from ops_engine.store.tables import engine_runs
from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_store.team_scope import acting_as

AT = "2026-11-16T00:00:00+00:00"
TEAM, OTHER = "team_ops", "team_lending"


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def _run(tx: EngineTransactions, team: str, run_id: str, status: str) -> None:
    row: dict[str, Any] = {
        "id": f"{run_id}_{tx.tenant()}",
        "team_id": team,
        "workflow_id": "wf_levy",
        "version": 1,
        "digest": "d",
        "run_key": f"{run_id}_{tx.tenant()}",
        "mode": "live",
        "status": status,
        "created_by": "a@x.example",
        "created_at": AT,
        "updated_at": AT,
    }
    async with tx.tenant_tx() as c:
        await c.execute(engine_runs.insert().values(tenant_id=tx.tenant(), **row))


async def test_the_page_and_counts_hold_the_acting_team_when_the_policy_lets_every_team_through(
    engine: AsyncEngine,
) -> None:
    tenant, tx = f"t_{uuid4().hex[:10]}", EngineTransactions(engine)
    with isolation.scope(tenant, TEAM):
        for run_id, status in (("run_a", "failed"), ("run_c", "failed"), ("run_b", "succeeded")):
            await _run(tx, TEAM, run_id, status)
    with isolation.scope(tenant, OTHER):
        await _run(tx, OTHER, "run_z", "failed")
    # Tenant-wide with a team acting, so the database policy lets every team through and the query alone holds them.
    with (
        isolation.tenant_wide("a test reads the runs list with every team let through", tenant_id=tenant),
        acting_as(TEAM),
    ):
        failed = await RunStore(tx).listed(ListParams(filters={"status": ["failed"]}), workflow_id="wf_levy")
    # One moment for every run, so the order is by id, in the list's newest-first direction.
    assert ([r["id"] for r in failed["data"]], failed["pagination"]["total"], failed["facets"]) == (
        [f"run_c_{tenant}", f"run_a_{tenant}"],
        2,
        {"status": {"failed": 2, "succeeded": 1}},
    )
