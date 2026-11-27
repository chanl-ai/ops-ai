"""Saved schedules, by failure mode: a slow machine overwrites a newer slot outcome, so a slot that ran reads as
skipped; a builder's save wipes the clock's slot state or loses the old rule the audit entry needs; one tenant reads
another's schedule. Runs on the migrated test database, PostgreSQL or SQL Server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.schedules import WorkflowSchedules
from ops_agents.store.tenancy import tenant_scope


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_one_slot_gets_one_outcome_and_a_save_keeps_the_slot_state(engine: AsyncEngine) -> None:
    tenant, other = f"a-{uuid4().hex[:8]}", f"b-{uuid4().hex[:8]}"
    wf = f"wf_{uuid4().hex[:10]}"
    store = WorkflowSchedules(engine)
    every_15: dict[str, JsonValue] = {
        "kind": "every",
        "every": 15,
        "unit": "minutes",
        "tz": "UTC",
        "anchor": "2026-11-23",
    }
    with tenant_scope(tenant):
        assert await store.save(wf, "start", "team_pay", every_15, "user_ana") is None
        slot = "2026-11-23T10:30:00+00:00"
        first = await store.record_slot(wf, "start", expected=None, slot=slot, outcome="ran", digest="d1", run_id="r1")
        late = await store.record_slot(
            wf, "start", expected=None, slot=slot, outcome="skipped", digest="d1", run_id=None
        )
        assert (first, late) == (True, False), "the machine that read the slot before it moved loses"
        row = await store.get(wf, "start")
        assert row is not None
        assert (row.last_slot_at, row.last_outcome, row.last_run_id) == (slot, "ran", "r1")

        hourly: dict[str, JsonValue] = {"kind": "hourly", "every": 1}
        assert await store.save(wf, "start", "team_pay", hourly, "user_ben") == every_15, "the old rule, for the audit"
        row = await store.get(wf, "start")
        assert row is not None
        assert (row.rule, row.changed_by, row.last_slot_at, row.rule_digest) == (
            hourly,
            "user_ben",
            "2026-11-23T10:30:00+00:00",
            "d1",
        )
    with tenant_scope(other):
        assert await store.get(wf, "start") is None
    with tenant_scope(tenant):
        assert await store.clear(wf, "start")
        assert await store.get(wf, "start") is None
