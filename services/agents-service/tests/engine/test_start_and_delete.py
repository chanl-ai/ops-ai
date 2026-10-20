"""A run start and a workflow delete never leave a run pinned to a deleted version: the start locks the version it
pins and the delete locks every version before it counts runs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope, tenant_tx
from ops_engine.store import DefinitionGoneError, DefinitionStore, RunStore
from ops_engine.store.tables import engine_definitions, engine_runs


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


def run_row(wf: str) -> dict[str, object]:
    rid = f"wfrun_{uuid4().hex[:10]}"
    return {
        "id": rid,
        "team_id": "t",
        "workflow_id": wf,
        "version": 1,
        "digest": "d" * 64,
        "run_key": rid,
        "mode": "live",
        "input": {},
        "created_by": "a@x",
    }


async def publish(tx: EngineTransactions, wf: str) -> None:
    await DefinitionStore(tx).publish(wf, name="W", definition={}, digest="d" * 64, now="now", by="a")


async def test_a_start_after_the_delete_is_refused(engine: AsyncEngine) -> None:
    tx, wf = EngineTransactions(engine), f"wf_{uuid4().hex[:8]}"
    with tenant_scope(f"t-{uuid4().hex[:6]}"):
        await publish(tx, wf)
        assert await DefinitionStore(tx).delete_draft(wf) == "deleted"
        with pytest.raises(DefinitionGoneError):
            await RunStore(tx).create(run_row(wf))


async def test_a_delete_waits_for_a_start_holding_the_version_and_then_keeps_it(engine: AsyncEngine) -> None:
    tenant, tx, wf = f"t-{uuid4().hex[:6]}", EngineTransactions(engine), f"wf_{uuid4().hex[:8]}"
    with tenant_scope(tenant):
        await publish(tx, wf)
        # A start mid-flight: its transaction holds the version's lock and has not inserted its run yet.
        async with tenant_tx(engine) as held:
            q = sa.select(engine_definitions.c.version).where(engine_definitions.c.workflow_id == wf)
            await held.execute(q.with_for_update())
            deleting = asyncio.create_task(DefinitionStore(tx).delete_draft(wf))
            await asyncio.sleep(0.3)
            assert not deleting.done(), "the delete waits for the start's lock"
            await held.execute(
                engine_runs.insert().values(
                    **run_row(wf), tenant_id=tenant, status="queued", created_at="now", updated_at="now"
                )
            )
        assert await deleting == "has_runs"
