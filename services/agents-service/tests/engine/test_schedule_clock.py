"""The schedule clock, by failure mode: it starts no run, too few, or in the wrong team; a new schedule runs at once; a
paused workflow ticks or Resume runs at once; an overlapping tick starts a second run, or a stuck run blocks for good;
an outage replays every missed slot; the clock keeps an old rule, ticks an archived workflow or forgets a restored one;
one refused schedule stops or floods the pass. Each pass is driven at a chosen minute, through the real store, lease
and run start, on an in-memory database."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.schedule_clock import ScheduleClock
from ops_agents.store.base import metadata
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.leases import Leases
from ops_agents.store.schedules import WorkflowSchedules
from ops_agents.store.tenancy import tenant_scope
from ops_agents.store.trigger_events import TriggerEvents
from ops_engine.store import DefinitionStore, RunStore
from ops_engine.store import metadata as engine_metadata
from ops_store.schedule import default_kinds

TENANT, TEAM, OTHER = "acme", "team_pay", "team_claims"
EVERY_15: dict[str, JsonValue] = {"kind": "every", "every": 15, "unit": "minutes"}
HOURLY: dict[str, JsonValue] = {"kind": "hourly", "every": 1}


def at(hhmm: str, day: str = "2026-11-23") -> datetime:
    return datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=UTC)


@dataclass
class Env:
    db: AsyncEngine

    def clock(self, owner: str = "worker:a") -> ScheduleClock:
        return ScheduleClock(self.db, Leases(self.db, owner=owner, ttl=30))

    async def publish(self, wid: str = "held_wires", *, team: str | None = TEAM, schema: Any = None) -> None:
        params: dict[str, Any] = {"inputSchema": schema} if schema else {}
        d: dict[str, Any] = {
            "schemaVersion": 2,
            "id": wid,
            "name": "Held wires",
            "nodes": [
                {
                    "id": "start",
                    "type": "ops.trigger.schedule",
                    "typeVersion": 1,
                    "name": "Schedule",
                    "parameters": params,
                },
                {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
            ],
            "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
        }
        store = DefinitionStore(EngineTransactions(self.db))
        with tenant_scope(TENANT):
            digest = hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()
            version, _ = await store.publish(
                wid, name="Held wires", definition=d, digest=digest, now="n", by="b", team=team
            )
            await store.go_live(wid, version)

    async def save(self, rule: dict[str, JsonValue], now: datetime, wid: str = "held_wires", team: str = TEAM) -> None:
        stored = default_kinds().checked(rule | {"tz": "UTC"}, now, floor=default_floor())
        with tenant_scope(TENANT):
            await WorkflowSchedules(self.db).save(wid, "start", team, stored, "user_ana")

    async def runs(self, wid: str = "held_wires") -> list[dict[str, Any]]:
        with tenant_scope(TENANT):
            rows = await RunStore(EngineTransactions(self.db)).list(workflow_id=wid)
        return sorted((r.model_dump() for r in rows), key=lambda r: r["run_key"])

    async def set_status(self, run_id: str, status: str) -> None:
        async with self.db.begin() as c:
            await c.execute(sa.text("UPDATE engine_runs SET status = :s WHERE id = :i"), {"s": status, "i": run_id})

    async def finish_all(self, wid: str = "held_wires") -> None:
        for r in await self.runs(wid):
            await self.set_status(r["id"], "succeeded")

    async def events(self, wid: str = "held_wires") -> list[dict[str, Any]]:
        with tenant_scope(TENANT):
            rows, _ = await TriggerEvents(self.db).page(wid, team_id=TEAM, page=1, page_size=50)
        return rows

    async def minutes(self, clock: ScheduleClock, start: str, end: str, *, finish: bool = True) -> None:
        h, m = map(int, start.split(":"))
        while f"{h:02d}:{m:02d}" <= end:
            await clock.pass_once(at(f"{h:02d}:{m:02d}"))
            if finish:
                await self.finish_all()
            h, m = (h + 1, 0) if m == 59 else (h, m + 1)


def default_floor() -> timedelta:
    return timedelta(minutes=5)


@pytest.fixture
async def env() -> AsyncIterator[Env]:
    db = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with db.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    yield Env(db)
    await db.dispose()


async def test_every_15_minutes_starts_four_runs_an_hour_in_the_workflows_team(env: Env) -> None:
    await env.publish()
    await env.save(EVERY_15, at("09:50"))
    clock = env.clock()
    await clock.pass_once(at("09:59"))
    await env.minutes(clock, "10:00", "10:59")
    runs = await env.runs()
    assert [r["run_key"] for r in runs] == [f"schedule:held_wires:2026-11-23T10:{m}Z" for m in ("00", "15", "30", "45")]
    assert {(r["team_id"], r["created_by"], r["mode"]) for r in runs} == {(TEAM, "trigger:schedule:held_wires", "live")}
    assert runs[0]["input"] == {"dueAt": "2026-11-23T10:00:00Z"}
    with tenant_scope(TENANT):
        mine = await RunStore(EngineTransactions(env.db)).list(workflow_id="held_wires", team_id=OTHER)
    assert mine == []


async def test_a_new_schedule_waits_for_its_next_slot(env: Env) -> None:
    await env.publish()
    await env.save(HOURLY, at("10:07"))
    clock = env.clock()
    await clock.pass_once(at("10:08"))
    await clock.pass_once(at("10:59"))
    assert await env.runs() == []
    await clock.pass_once(at("11:00"))
    assert len(await env.runs()) == 1


async def test_a_paused_workflow_sends_nothing_and_resume_waits_for_the_next_slot(env: Env) -> None:
    await env.publish()
    await env.save(EVERY_15, at("09:50"))
    clock = env.clock()
    await env.minutes(clock, "09:59", "10:00")
    assert len(await env.runs()) == 1
    store = DefinitionStore(EngineTransactions(env.db))
    with tenant_scope(TENANT):
        await store.set_paused("held_wires", True)
    await env.minutes(clock, "10:01", "10:16")
    assert len(await env.runs()) == 1
    with tenant_scope(TENANT):
        await store.set_paused("held_wires", False)
    await env.minutes(clock, "10:18", "10:29")
    assert len(await env.runs()) == 1, "Resume does not run the slot it missed"
    await clock.pass_once(at("10:30"))
    assert len(await env.runs()) == 2


async def test_a_running_run_skips_the_tick_and_a_stuck_one_does_not(env: Env) -> None:
    await env.publish()
    await env.save(EVERY_15, at("09:50"))
    clock = env.clock()
    await clock.pass_once(at("09:59"))
    await clock.pass_once(at("10:00"))
    [first] = await env.runs()
    await env.set_status(first["id"], "running")
    await clock.pass_once(at("10:15"))
    assert len(await env.runs()) == 1
    [skipped] = await env.events()
    assert skipped["outcome"] == "skipped" and "still going" in skipped["detail"]["reason"]
    await env.set_status(first["id"], "stuck")
    await clock.pass_once(at("10:30"))
    assert len(await env.runs()) == 2


async def test_after_an_outage_one_catch_up_run_starts_marked_late(env: Env) -> None:
    await env.publish()
    await env.save(EVERY_15, at("06:50"))
    await env.minutes(env.clock(), "06:59", "07:00")
    later = env.clock()  # the worker came back: a new process
    await later.pass_once(at("10:02"))
    runs = await env.runs()
    assert [r["input"]["dueAt"] for r in runs] == ["2026-11-23T07:00:00Z", "2026-11-23T10:00:00Z"]
    [late] = await env.events()
    assert late["outcome"] == "late" and late["run_id"] == runs[1]["id"]


async def test_the_clock_follows_the_saved_rule_and_archive_and_restore(env: Env) -> None:
    await env.publish()
    await env.save(EVERY_15, at("09:50"))
    clock = env.clock()
    await env.minutes(clock, "09:59", "10:06")
    await env.save(HOURLY, at("10:07"))
    await env.minutes(clock, "10:08", "11:00")
    assert [r["run_key"][-6:] for r in await env.runs()] == ["10:00Z", "11:00Z"]
    store = DefinitionStore(EngineTransactions(env.db))
    with tenant_scope(TENANT):
        await store.set_archived("held_wires", True, by="b", now="n")
    await env.minutes(clock, "11:58", "12:01")
    assert len(await env.runs()) == 2, "an archived workflow does not tick"
    with tenant_scope(TENANT):
        await store.set_archived("held_wires", False, by="b", now="n")
    await env.minutes(clock, "12:10", "12:11")
    assert len(await env.runs()) == 2, "a restore waits for the next slot"
    await clock.pass_once(at("13:00"))
    assert len(await env.runs()) == 3


async def test_a_refused_schedule_does_not_stop_the_next_and_is_not_retried(env: Env) -> None:
    await env.publish("needs_day", schema={"type": "object", "required": ["day"], "properties": {"day": {}}})
    await env.publish("held_wires")
    await env.save(EVERY_15, at("09:50"), wid="needs_day")
    await env.save(EVERY_15, at("09:50"))
    clock = env.clock()
    await clock.pass_once(at("09:59"))
    await clock.pass_once(at("10:00"))
    await clock.pass_once(at("10:01"))
    assert len(await env.runs()) == 1
    with tenant_scope(TENANT):
        refused, _ = await TriggerEvents(env.db).page("needs_day", team_id=TEAM, page=1, page_size=50)
    assert [e["outcome"] for e in refused] == ["refused"]
