"""The schedule clock, by failure mode: it starts no run, too few, or in the wrong team; a new schedule runs at once, or
a rule whose first slot is ahead never runs; a paused workflow ticks or Resume runs at once; the clock keeps an old
rule, ticks an archived workflow or forgets a restored one; an overlapping tick starts a second run, or a stuck run
blocks for good; an outage replays every missed slot, or one past half the interval runs; one refused or failing
schedule stops or floods the pass, or a failed or held tick loses its slot. Each pass is driven at a chosen minute,
through the real store, lease and run start, on an in-memory database."""

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

from ops_agents.api.schedule_clock import KEY, SCHEDULE_TRIGGER, ScheduleClock, Tick, WorkflowStart, lease_key
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

    def clock(self, owner: str = "worker:a", handler: Any = None) -> ScheduleClock:
        handlers = {SCHEDULE_TRIGGER: handler} if handler else None
        return ScheduleClock(self.db, Leases(self.db, owner=owner, ttl=30), handlers=handlers)

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

    async def save(
        self, rule: dict[str, JsonValue], now: datetime, wid: str = "held_wires", floor: timedelta | None = None
    ) -> None:
        stored = default_kinds().checked(rule | {"tz": "UTC"}, now, floor=floor or default_floor())
        with tenant_scope(TENANT):
            await WorkflowSchedules(self.db).save(wid, "start", TEAM, stored, "user_ana")

    async def saved_at(self, wid: str, when: str) -> None:
        """The rule was saved at `when`: the store stamps the real time, a test drives the clock in 2026-11-23."""
        async with self.db.begin() as c:
            await c.execute(
                sa.text("UPDATE workflow_schedules SET changed_at = :w WHERE workflow_id = :i"), {"w": when, "i": wid}
            )

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


async def test_every_15_minutes_starts_four_runs_an_hour_in_the_workflows_team_and_a_running_one_skips(
    env: Env,
) -> None:
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

    # A run still going skips the next tick; a stuck one does not.
    await env.publish("busy")
    await env.save(EVERY_15, at("09:50"), "busy")
    await clock.pass_once(at("09:59"))
    await clock.pass_once(at("10:00"))
    [first] = await env.runs("busy")
    await env.set_status(first["id"], "running")
    await clock.pass_once(at("10:15"))
    assert len(await env.runs("busy")) == 1
    [skipped] = await env.events("busy")
    assert skipped["outcome"] == "skipped" and "still going" in skipped["detail"]["reason"]
    await env.set_status(first["id"], "stuck")
    await clock.pass_once(at("10:30"))
    assert len(await env.runs("busy")) == 2


async def test_a_new_schedule_waits_for_its_next_slot_and_runs_a_first_slot_ahead(env: Env) -> None:
    await env.publish()
    await env.publish("evening")
    await env.save(HOURLY, at("10:07"))
    # Saved at 10:07 with no slot yet: its first slot is 18:00 today.
    await env.save({"kind": "every", "every": 1, "unit": "days", "start": "18:00"}, at("10:07"), wid="evening")
    clock = env.clock()
    await clock.pass_once(at("10:08"))
    await clock.pass_once(at("10:59"))
    assert await env.runs() == [] and await env.runs("evening") == []
    await clock.pass_once(at("11:00"))
    assert len(await env.runs()) == 1
    await clock.pass_once(at("17:59"))
    await clock.pass_once(at("18:00"))
    assert [r["run_key"] for r in await env.runs("evening")] == ["schedule:evening:2026-11-23T18:00Z"]

    # Saved 20 seconds before its slot, first seen 10 seconds after it: that slot is the rule's own first, so it runs.
    await env.publish("last_minute")
    await env.save(EVERY_15, at("11:59:40"), "last_minute")
    await env.saved_at("last_minute", "2026-11-23T11:59:40.000Z")
    await clock.pass_once(at("12:00:10"))
    assert [r["run_key"] for r in await env.runs("last_minute")] == ["schedule:last_minute:2026-11-23T12:00Z"]


async def test_pause_rule_change_archive_and_restore_each_wait_for_the_next_slot(env: Env) -> None:
    await env.publish()
    await env.save(EVERY_15, at("09:50"))
    clock = env.clock()
    await env.minutes(clock, "09:59", "10:00")
    assert len(await env.runs()) == 1
    store = DefinitionStore(EngineTransactions(env.db))
    with tenant_scope(TENANT):
        await store.set_paused("held_wires", True)
    await env.minutes(clock, "10:01", "10:16")
    assert len(await env.runs()) == 1, "a paused workflow does not tick"
    with tenant_scope(TENANT):
        await store.set_paused("held_wires", False)
    await env.minutes(clock, "10:18", "10:29")
    assert len(await env.runs()) == 1, "Resume does not run the slot it missed"
    await env.minutes(clock, "10:30", "10:36")
    assert len(await env.runs()) == 2
    await env.save(HOURLY, at("10:37"))
    await env.minutes(clock, "10:38", "11:00")
    assert [r["run_key"][-6:] for r in await env.runs()] == ["10:00Z", "10:30Z", "11:00Z"], "the saved rule wins"
    with tenant_scope(TENANT):
        await store.set_archived("held_wires", True, by="b", now="n")
    await env.minutes(clock, "11:58", "12:01")
    assert len(await env.runs()) == 3, "an archived workflow does not tick"
    with tenant_scope(TENANT):
        await store.set_archived("held_wires", False, by="b", now="n")
    await env.minutes(clock, "12:10", "12:11")
    assert len(await env.runs()) == 3, "a restore waits for the next slot"
    await clock.pass_once(at("13:00"))
    assert len(await env.runs()) == 4

    # A rule changed while paused and resumed within a minute of its slot still waits for the next slot.
    await env.publish("edited_paused")
    await env.save(EVERY_15, at("09:50"), "edited_paused")
    await env.minutes(clock, "09:59", "10:00")
    with tenant_scope(TENANT):
        await store.set_paused("edited_paused", True)
    await env.save(HOURLY, at("10:50"), "edited_paused")
    await env.saved_at("edited_paused", "2026-11-23T10:50:00.000Z")
    await clock.pass_once(at("10:55"))
    await env.finish_all("edited_paused")
    with tenant_scope(TENANT):
        await store.set_paused("edited_paused", False)
    await clock.pass_once(at("11:00:20"))
    assert len(await env.runs("edited_paused")) == 1, "a resume waits, whatever changed while paused"
    await clock.pass_once(at("12:00"))
    assert len(await env.runs("edited_paused")) == 2


async def test_after_an_outage_one_catch_up_run_starts_marked_late_and_an_older_slot_is_missed(env: Env) -> None:
    await env.publish()
    await env.save(EVERY_15, at("06:50"))
    await env.minutes(env.clock(), "06:59", "07:00")
    later = env.clock()  # the worker came back: a new process
    await later.pass_once(at("10:02"))
    runs = await env.runs()
    assert [r["input"]["dueAt"] for r in runs] == ["2026-11-23T07:00:00Z", "2026-11-23T10:00:00Z"]
    [late] = await env.events()
    assert late["outcome"] == "late" and late["run_id"] == runs[1]["id"]
    await env.finish_all()
    await env.clock().pass_once(at("10:38"))  # down again: 10:30 is 8 minutes old, past half of 15
    assert len(await env.runs()) == 2
    assert [e["outcome"] for e in await env.events()] == ["missed", "late"]
    await env.clock().pass_once(at("10:45"))
    assert len(await env.runs()) == 3, "the slot after a missed one runs"

    # A pass lands up to a minute after a slot; for a one-minute rule that is past half the interval, not an outage.
    await env.publish("each_minute")
    await env.save({"kind": "every", "every": 1, "unit": "minutes"}, at("10:50"), "each_minute", timedelta(minutes=1))
    clock = env.clock()
    await clock.pass_once(at("10:50:45"))
    await clock.pass_once(at("10:51:45"))
    assert [r["input"]["dueAt"] for r in await env.runs("each_minute")] == ["2026-11-23T10:51:00Z"]

    # Friday's slot of a weekday rule is 24 hours after Thursday's and 72 before Monday's: Saturday evening is past half
    # the smaller gap, so it is missed, not run late.
    weekdays: dict[str, JsonValue] = {
        "kind": "every",
        "every": 1,
        "unit": "days",
        "start": "18:00",
        "days": ["mon", "tue", "wed", "thu", "fri"],
    }
    await env.publish("weekdays")
    await env.save(weekdays, at("17:00", "2026-11-26"), "weekdays")
    await env.clock().pass_once(at("17:30", "2026-11-26"))
    await env.clock().pass_once(at("20:00", "2026-11-28"))
    assert await env.runs("weekdays") == []
    assert [e["outcome"] for e in await env.events("weekdays")] == ["missed"]


class Explodes(WorkflowStart):
    """The workflow start, failing with an error no refusal names for the workflows in `failing`."""

    def __init__(self, env: Env, failing: set[str]) -> None:
        super().__init__(RunStore(EngineTransactions(env.db)))
        self.failing = failing

    async def tick(self, tick: Tick) -> str | None:
        if tick.schedule.workflow_id in self.failing:
            raise RuntimeError("the database went away")
        return await super().tick(tick)


async def test_a_refused_failing_or_held_schedule_does_not_stop_the_next_and_keeps_its_slot(env: Env) -> None:
    # Sorted before the healthy one, so each failure happens first in the pass.
    await env.publish("a_needs_day", schema={"type": "object", "required": ["day"], "properties": {"day": {}}})
    await env.publish("b_fails")
    await env.publish("c_held")
    await env.publish("held_wires")
    for wid in ("a_needs_day", "b_fails", "c_held", "held_wires"):
        await env.save(EVERY_15, at("09:50"), wid=wid)
    handler = Explodes(env, {"b_fails"})
    clock = env.clock(handler=handler)
    await clock.pass_once(at("09:59"))
    other = Leases(env.db, owner="worker:b", ttl=30)
    await other.acquire(lease_key(TENANT, "c_held", "start"), KEY)
    await clock.pass_once(at("10:00"))
    assert len(await env.runs()) == 1 and await env.runs("b_fails") == [] and await env.runs("c_held") == []
    await other.release(lease_key(TENANT, "c_held", "start"), KEY)
    handler.failing.clear()
    await clock.pass_once(at("10:01"))
    assert [len(await env.runs(w)) for w in ("b_fails", "c_held")] == [1, 1], "a failed or held tick keeps its slot"
    assert await env.runs("a_needs_day") == []
    with tenant_scope(TENANT):
        refused, _ = await TriggerEvents(env.db).page("a_needs_day", team_id=TEAM, page=1, page_size=50)
    assert [e["outcome"] for e in refused] == ["refused"], "a refusal is recorded once and not tried again"
