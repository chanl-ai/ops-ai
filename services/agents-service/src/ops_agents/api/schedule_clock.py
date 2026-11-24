"""The schedule clock: every minute it reads each saved schedule (store/schedules.py) whose workflow has a live version
that still has the trigger step, asks the rule kind registry for the schedule's latest slot, and hands a slot not yet
counted to the handler for the trigger's target kind. It reads live versions each pass, as the mail listener does, so
going live, pause, archive and restore need no write here: a paused or archived workflow is not live and sends
nothing.

One slot gives at most one run and one outcome: a lease per schedule around "busy? start, record", a slot write that
names the slot it read, and the run key `schedule:{workflow}:{slot in UTC to the minute}`.

A schedule first seen live (new, changed, resumed or restored) records its current slot and starts nothing, so it
first runs at its next slot. "First seen" means the rule differs from the one its last slot was counted against, or
the row was not seen at this clock's previous pass. A clock that has just started has no previous pass, so after an
outage it starts one catch-up run, marked late, when the latest slot is within half the interval; an older slot is
recorded as missed.

The clock knows no rule's fields (the registry answers) and no target's work (the handler answers). Scheduled runs act
for no person: each is started by `trigger:schedule:{workflow}`."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from ops_engine.store import DefinitionRow, DefinitionStore, RunStore
from ops_service_kit.errors import ApiError
from ops_service_kit.http import Json
from ops_service_kit.logging import get_logger
from ops_store import background, isolation
from ops_store.schedule import ScheduleKinds, default_kinds

from ..store.engine import EngineTransactions
from ..store.leases import LeaseHeldError, Leases
from ..store.schedules import ScheduleRow, WorkflowSchedules
from ..store.tenancy import SCHEDULE_CLOCK
from ..store.trigger_events import KEEP_SCHEDULE_DAYS, SCHEDULE_SOURCE, Outcome, TriggerEvent, TriggerEvents
from .email_trigger import POLL_LEASE_PREFIX, outage
from .engine_runs import start_run

log = get_logger("ops_agents.api.schedule_clock")

KEY = "schedule_clock"
EVERY_S = 60.0
SCHEDULE_TRIGGER = "ops.trigger.schedule"
# A run started this long after its slot is marked late on the trigger list.
LATE_AFTER = timedelta(seconds=90)
# A run that blocks the next tick: one a worker has or will pick up. Waiting for a person and Stuck do not block, or
# one stuck run would stop the schedule for good.
BUSY = ("queued", "running")


# The one input field the clock fills.
CLOCK_FIELDS = frozenset({"dueAt"})


def required_beyond_due(definition: Json, step: str) -> str | None:
    """The first field the step's input schema requires that a tick cannot fill, or None: every tick would fail on
    it, so a save and a publish refuse it."""
    for node in cast(list[Json], definition.get("nodes") or []):
        if node.get("id") == step:
            schema = cast(Json, cast(Json, node.get("parameters") or {}).get("inputSchema") or {})
            extra = sorted(set(cast(list[str], schema.get("required") or [])) - CLOCK_FIELDS)
            return extra[0] if extra else None
    return None


def iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def digest(rule: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(rule, sort_keys=True).encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Tick:
    """One slot of one schedule, as a handler sees it."""

    schedule: ScheduleRow
    definition: DefinitionRow
    slot: datetime


class Refused(Exception):
    """A tick the target will not start for a reason the next slot can fix; recorded once, with its code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TargetHandler(Protocol):
    """What a target kind answers: whether its last tick is still going, and doing this tick (returning a run id, or
    None when the work has no run)."""

    async def busy(self, tick: Tick) -> bool: ...

    async def tick(self, tick: Tick) -> str | None: ...


class WorkflowStart:
    """The workflow target: each tick starts one live run keyed by the workflow and the slot."""

    def __init__(self, runs: RunStore) -> None:
        self.runs = runs

    async def busy(self, tick: Tick) -> bool:
        # The last run a tick started, carried past skipped and refused slots, so two skips in a row still see it.
        last = tick.schedule.last_run_id
        if not last:
            return False
        run = await self.runs.row(last)
        return run is not None and run.status in BUSY

    async def tick(self, tick: Tick) -> str | None:
        wid = tick.definition.workflow_id
        if not tick.definition.team_id:
            raise Refused("schedule_needs_team", "A scheduled run needs a team, and this workflow belongs to none.")
        run, _ = await start_run(
            self.runs,
            tick.definition,
            team_id=tick.definition.team_id,
            mode="live",
            input={"dueAt": iso(tick.slot)},
            run_key=f"schedule:{wid}:{iso(tick.slot)[:16]}Z",
            created_by=f"trigger:schedule:{wid}",
            started_via="schedule",
        )
        return run.id


class ScheduleClock:
    def __init__(
        self,
        db: Any,
        leases: Leases,
        *,
        kinds: ScheduleKinds | None = None,
        handlers: Mapping[str, TargetHandler] | None = None,
    ) -> None:
        """`kinds` are the rule kinds the clock reads rules with; `handlers` maps a trigger node type to its target.
        Both default to the built-ins; a test adds its own beside them."""
        self.db = db
        self.leases = leases
        self.kinds = kinds or default_kinds()
        runs = RunStore(EngineTransactions(db))
        self.handlers: Mapping[str, TargetHandler] = handlers or {SCHEDULE_TRIGGER: WorkflowStart(runs)}
        self.schedules = WorkflowSchedules(db)
        self.events = TriggerEvents(db)
        self.last_pass: datetime | None = None
        self._forgot: dict[str, datetime] = {}

    async def pass_once(self, now: datetime | None = None) -> int:
        """One pass at `now`; returns the runs it started. One schedule's failure never stops the others."""
        now = now or datetime.now(UTC)
        live: dict[str, dict[str, DefinitionRow]] = {}
        for row in await DefinitionStore(EngineTransactions(self.db)).live_everywhere():
            live.setdefault(row.tenant_id, {})[row.workflow_id] = row
        started = 0
        for tenant, workflows in live.items():
            with isolation.tenant_wide(SCHEDULE_CLOCK, tenant_id=tenant):
                for s in await self.schedules.everything():
                    definition = workflows.get(s.workflow_id)
                    if definition is None or (handler := self._handler(definition, s.trigger_step)) is None:
                        continue  # not live, or the live version no longer has the step: idle
                    try:
                        started += await self._one(s, definition, handler, now)
                    except Exception as e:
                        log.exception("schedule_tick_failed", workflow=s.workflow_id, error=type(e).__name__)
        self.last_pass = now
        return started

    def _handler(self, definition: DefinitionRow, step: str) -> TargetHandler | None:
        nodes = cast(list[Json], definition.definition.get("nodes") or [])
        for node in nodes:
            if node.get("id") == step:
                return self.handlers.get(str(node.get("type")))
        return None

    async def _one(self, s: ScheduleRow, definition: DefinitionRow, handler: TargetHandler, now: datetime) -> int:
        slot = self.kinds.last_slot(s.rule, now)
        at = iso(now)
        if slot is None:
            return 0
        lease = (
            POLL_LEASE_PREFIX
            + "s"
            + hashlib.sha256(f"{definition.tenant_id}:{s.workflow_id}:{s.trigger_step}".encode()).hexdigest()[:31]
        )
        try:
            await self.leases.acquire(lease, KEY)
        except LeaseHeldError:
            return 0  # another machine has this schedule this minute
        try:
            # Read again under the lease: the row read before it may be another machine's outcome behind.
            fresh = await self.schedules.get(s.workflow_id, s.trigger_step)
            if fresh is None:
                return 0
            return await self._tick(fresh, definition, handler, slot=slot, now=now, at=at)
        finally:
            await self.leases.release(lease, KEY)

    async def _tick(
        self,
        s: ScheduleRow,
        definition: DefinitionRow,
        handler: TargetHandler,
        *,
        slot: datetime,
        now: datetime,
        at: str,
    ) -> int:
        rule_digest = digest(s.rule)
        key = (s.workflow_id, s.trigger_step)
        first_sight = (
            s.rule_digest != rule_digest
            or s.last_slot_at is None
            or (self.last_pass is not None and (s.seen_at is None or s.seen_at < iso(self.last_pass)))
        )

        async def record(outcome: str, run_id: str | None = None) -> bool:
            # A slot that started nothing keeps the last run's id: that run is what the next tick asks about.
            return await self.schedules.record_slot(
                *key,
                expected=s.last_slot_at,
                slot=iso(slot),
                outcome=outcome,
                digest=rule_digest,
                run_id=run_id or s.last_run_id,
                at=at,
            )

        if first_sight:
            await record("seen")
            return 0
        if s.last_slot_at is not None and iso(slot) <= s.last_slot_at:
            await self.schedules.seen(*key, at)
            return 0
        await self._forget_old(s, now)
        tick = Tick(s, definition, slot)
        upcoming = self.kinds.next_slots(s.rule, slot, 1)
        if upcoming and now - slot > (upcoming[0] - slot) / 2:
            if await record("missed"):
                await self._log(
                    tick, "missed", reason="The clock was down past half the interval, so this slot did not run."
                )
            return 0
        if await handler.busy(tick):
            if await record("skipped"):
                await self._log(tick, "skipped", reason="The last scheduled run was still going.")
            return 0
        try:
            run_id = await handler.tick(tick)
        except (Refused, ApiError) as e:
            if outage(e):
                raise
            if await record("refused"):
                await self._log(tick, "refused", reason=str(e), code=getattr(e, "code", "refused"))
            return 0
        late = now - slot > LATE_AFTER
        await record("late" if late else "ran", run_id)
        if late:
            await self._log(tick, "late", reason=f"Started {iso(now)}, after the clock was down.", run_id=run_id)
        return 1

    async def _log(
        self, tick: Tick, outcome: Outcome, *, reason: str, code: str | None = None, run_id: str | None = None
    ) -> None:
        detail: Json = {"reason": reason, "dueAt": iso(tick.slot)}
        if code:
            detail["code"] = code
        await self.events.add(
            TriggerEvent(
                team_id=tick.schedule.team_id,
                workflow_id=tick.schedule.workflow_id,
                source=f"{SCHEDULE_SOURCE}{tick.schedule.trigger_step}",
                event_key=f"schedule:{tick.schedule.workflow_id}:{iso(tick.slot)[:16]}Z",
                sender="",
                subject=self.kinds.words(tick.schedule.rule),
                received_at=iso(tick.slot),
                outcome=outcome,
                run_id=run_id,
                detail=detail,
            )
        )

    async def _forget_old(self, s: ScheduleRow, now: datetime) -> None:
        """Drops the workflow's schedule rows older than KEEP_SCHEDULE_DAYS, once an hour."""
        last = self._forgot.get(s.workflow_id)
        if last is not None and now - last < timedelta(hours=1):
            return
        await self.events.forget_schedule_rows_before(s.workflow_id, iso(now - timedelta(days=KEEP_SCHEDULE_DAYS)))
        self._forgot[s.workflow_id] = now


async def keep_schedules_ticking(clock: ScheduleClock, stop: asyncio.Event, beats: background.HeartbeatStore) -> None:
    """The clock on the shared loop runner: a failing pass shows on Background and is retried with backoff."""

    async def once() -> int:
        return await clock.pass_once()

    await background.run(KEY, once, stop=stop, store=beats, every_s=EVERY_S)
