"""The schedule clock on the migrated test database, by failure mode: two machines on one slot start two runs, or record
a slot that ran as skipped; a dead clock looks healthy on Background."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.api.schedule_clock import ScheduleClock, keep_schedules_ticking
from ops_agents.store.background import heartbeats
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.leases import Leases
from ops_agents.store.schedules import WorkflowSchedules
from ops_agents.store.tenancy import tenant_scope
from ops_agents.store.trigger_events import TriggerEvents
from ops_engine.store import DefinitionStore, RunStore
from ops_store.schedule import default_kinds
from ops_store.testing import loop_reports_failure

TEAM = "team_pay"


def at(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"2026-11-23T{hhmm}").replace(tzinfo=UTC)


async def test_two_machines_on_one_slot_give_one_run_and_one_outcome(database_url: str) -> None:
    db = create_async_engine(database_url)
    tenant, wid = f"t-{uuid4().hex[:8]}", f"wf_{uuid4().hex[:8]}"
    d: dict[str, Any] = {
        "schemaVersion": 2,
        "id": wid,
        "name": "Held wires",
        "nodes": [
            {"id": "start", "type": "ops.trigger.schedule", "typeVersion": 1, "name": "Sched", "parameters": {}},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
        ],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }
    try:
        store = DefinitionStore(EngineTransactions(db))
        rule = default_kinds().checked(
            {"kind": "every", "every": 15, "unit": "minutes"}, at("09:50"), timedelta(minutes=5)
        )
        with tenant_scope(tenant):
            digest = hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()
            version, _ = await store.publish(
                wid, name="Held wires", definition=d, digest=digest, now="n", by="b", team=TEAM
            )
            await store.go_live(wid, version)
            await WorkflowSchedules(db).save(wid, "start", TEAM, rule, "user_ana")
        a = ScheduleClock(db, Leases(db, owner="worker:a", ttl=30))
        b = ScheduleClock(db, Leases(db, owner="worker:b", ttl=30))
        await a.pass_once(at("09:59"))
        await asyncio.gather(a.pass_once(at("10:00")), b.pass_once(at("10:00")))
        with tenant_scope(tenant):
            runs = await RunStore(EngineTransactions(db)).list(workflow_id=wid)
            row = await WorkflowSchedules(db).get(wid, "start")
            events, _ = await TriggerEvents(db).page(wid, team_id=TEAM, page=1, page_size=10)
        assert len(runs) == 1
        assert row is not None and (row.last_outcome, row.last_run_id) == ("ran", runs[0].id)
        assert events == []
    finally:
        await db.dispose()


async def test_a_failing_clock_pass_shows_on_health(client: AsyncClient, database_url: str) -> None:
    engine, stop, running = create_async_engine(database_url), asyncio.Event(), list[asyncio.Task[None]]()
    down = create_async_engine("postgresql+asyncpg://nobody@127.0.0.1:9/none")

    def trip() -> None:
        clock = ScheduleClock(down, Leases(down, owner="worker:a", ttl=30))
        running.append(asyncio.create_task(keep_schedules_ticking(clock, stop, heartbeats(engine))))

    try:
        await loop_reports_failure(client, "schedule_clock", trip, within_s=10)
    finally:
        stop.set()
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        await engine.dispose()
        await down.dispose()
