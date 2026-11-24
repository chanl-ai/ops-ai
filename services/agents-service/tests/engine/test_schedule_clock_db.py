"""The schedule clock on the migrated test database, by failure mode: two machines on one slot both tick it, so a slot
that ran reads as skipped; the worker never starts the clock; a dead clock looks healthy on Background. The slot write
that names the slot it read is proven in tests/store/test_workflow_schedules.py."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.api.schedule_clock import SCHEDULE_TRIGGER, ScheduleClock, Tick, WorkflowStart, keep_schedules_ticking
from ops_agents.api.worker import serve
from ops_agents.store.background import heartbeats
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.leases import Leases
from ops_agents.store.outbox import outbox_relay
from ops_agents.store.schedules import WorkflowSchedules
from ops_agents.store.tenancy import tenant_scope
from ops_agents.store.trigger_events import TriggerEvents
from ops_engine.store import DefinitionStore, RunStore
from ops_service_kit.settings import Settings
from ops_store.outbox import run_relay
from ops_store.schedule import default_kinds
from ops_store.testing import loop_reports_failure
from tests.conftest import SEED

TEAM = "team_pay"


class Held(WorkflowStart):
    """Machine a's target: holds inside its tick until the test lets go, so machine b's pass falls inside it."""

    def __init__(self, runs: RunStore) -> None:
        super().__init__(runs)
        self.inside, self.go = asyncio.Event(), asyncio.Event()

    async def tick(self, tick: Tick) -> str | None:
        self.inside.set()
        await self.go.wait()
        return await super().tick(tick)


class Behind(WorkflowStart):
    """Machine b's target, one step behind: it still sees the last run as going."""

    async def busy(self, tick: Tick) -> bool:
        return True


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
        runs = RunStore(EngineTransactions(db))
        held = Held(runs)
        a = ScheduleClock(db, Leases(db, owner="worker:a", ttl=30), handlers={SCHEDULE_TRIGGER: held})
        b = ScheduleClock(db, Leases(db, owner="worker:b", ttl=30), handlers={SCHEDULE_TRIGGER: Behind(runs)})
        await a.pass_once(at("09:59"))
        first = asyncio.create_task(a.pass_once(at("10:00")))
        await asyncio.wait_for(held.inside.wait(), 10)
        await b.pass_once(at("10:00"))  # inside a's tick: the lease is a's
        held.go.set()
        await first
        with tenant_scope(tenant):
            runs = await RunStore(EngineTransactions(db)).list(workflow_id=wid)
            row = await WorkflowSchedules(db).get(wid, "start")
            events, _ = await TriggerEvents(db).page(wid, team_id=TEAM, page=1, page_size=10)
        assert len(runs) == 1
        assert row is not None and (row.last_outcome, row.last_run_id) == ("ran", runs[0].id)
        assert events == []
    finally:
        await db.dispose()


async def test_the_worker_starts_the_clock_and_a_failing_pass_shows_on_health(
    client: AsyncClient, database_url: str
) -> None:
    engine, stop, running = create_async_engine(database_url), asyncio.Event(), list[asyncio.Task[None]]()
    down = create_async_engine("postgresql+asyncpg://nobody@127.0.0.1:9/none")

    def trip() -> None:
        clock = ScheduleClock(down, Leases(down, owner="worker:a", ttl=30))
        running.append(asyncio.create_task(keep_schedules_ticking(clock, stop, heartbeats(engine))))

    try:
        worker_stop = asyncio.Event()
        worker = asyncio.create_task(serve(Settings(database_url=database_url, seed_dir=SEED), worker_stop))
        try:
            for _ in range(100):
                if any(b.process == "schedule_clock" for b in await heartbeats(engine).read()):
                    break
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("the worker never wrote the schedule clock's heartbeat")
        finally:
            worker_stop.set()
            await asyncio.wait_for(worker, 30)
        await loop_reports_failure(client, "schedule_clock", trip, within_s=10)

        def trip_relay() -> None:
            hand_off = run_relay(outbox_relay(down, {}), key="agents_relay", stop=stop, store=heartbeats(engine))
            running.append(asyncio.create_task(hand_off))

        await loop_reports_failure(client, "agents_relay", trip_relay, within_s=10)
    finally:
        stop.set()
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        await engine.dispose()
        await down.dispose()
