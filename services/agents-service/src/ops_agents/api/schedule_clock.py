"""The schedule clock: every minute it reads each saved schedule (store/schedules.py) whose workflow has a live version
that still has the trigger step, asks the rule kind registry for the schedule's latest slot, and hands a slot not yet
counted to the handler for the trigger's target kind. It reads live versions each pass, as the mail listener does, so
going live, pause, archive and restore need no write here: a paused or archived workflow is not live and sends
nothing.

One slot gives at most one run and one outcome: a lease per schedule around "busy? start, record", a slot write that
names the slot it read, and the run key `schedule:{workflow}:{slot in UTC to the minute}`.

A schedule's first sighting (new, changed, resumed or restored) records its current slot, or with no slot yet the rule
it saw, and starts nothing, so it first runs at its next slot. It is read from the row, never from one machine's
memory: the rule differs from the one stored beside the slot, or `seen_at` is empty, which each pass makes it while
the workflow is not live or its live version lacks the step. A tick that fails, or whose lease another machine holds,
writes nothing, so its slot stays open and the next pass tries it again. After an outage the clock starts one catch-up
run, marked late, when the latest slot is within half the smaller gap to its neighbouring slots (never less than
LATE_AFTER, the most a normal pass trails its slot by); an older slot is recorded as missed. A rule saved shortly
before its slot runs that slot, as the pass that first sees it is still within LATE_AFTER of it.

The clock knows no rule's fields (the registry answers) and no target's work (the handler answers). Scheduled runs act
for no person: each is started by `trigger:schedule:{workflow}`."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast

from ops_engine.store import DefinitionRow, DefinitionStore, RunStore
from ops_service_kit.errors import ApiError
from ops_service_kit.http import Json
from ops_service_kit.logging import get_logger
from ops_store import background, isolation
from ops_store.schedule import KINDS, ScheduleKinds

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
# A run started this long after its slot is marked late on the trigger list; a slot is never missed sooner.
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


def slot_key(workflow_id: str, slot: str | datetime) -> str:
    """The key one slot of a workflow is known by: its run key and its row in the trigger's log. The slot is an instant
    or its `iso` text, to the minute."""
    text = iso(slot) if isinstance(slot, datetime) else slot
    return f"schedule:{workflow_id}:{text[:16]}Z"


def lease_key(tenant: str, workflow_id: str, step: str) -> str:
    """One schedule's lease, under the poll lease prefix the sweeper leaves alone."""
    return POLL_LEASE_PREFIX + "s" + hashlib.sha256(f"{tenant}:{workflow_id}:{step}".encode()).hexdigest()[:31]


def digest(rule: Json) -> str:
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
            run_key=slot_key(wid, tick.slot),
            created_by=f"trigger:schedule:{wid}",
            started_via="schedule",
        )
        return run.id


IdleCode = Literal["no_live_version", "paused", "step_missing", "not_schedulable"]


def idle_state(
    step: str, definition: Json | None, stage: str | None, takes: Callable[[Json], bool]
) -> tuple[IdleCode, str] | None:
    """Why a schedule on `step` starts nothing against the version serving its workflow, as a code and a sentence, or
    None while it ticks. `stage` is the serving version's (live or paused); `takes` says whether a step's node type is
    a trigger some target handles."""
    if definition is None:
        return "no_live_version", "No version is live yet; the schedule starts once one is."
    if stage != "live":
        return "paused", "The workflow is paused, so the schedule starts nothing until it is resumed."
    node = next((n for n in cast(list[Json], definition.get("nodes") or []) if n.get("id") == step), None)
    if node is None:
        return "step_missing", f"The live version has no step {step}, so this schedule starts nothing until one does."
    if not takes(node):
        return (
            "not_schedulable",
            f"Step {step} is no longer a schedule trigger in the live version, so this schedule starts nothing.",
        )
    return None


def idle_reason(step: str, definition: Json | None, stage: str | None, takes: Callable[[Json], bool]) -> str | None:
    """The sentence of `idle_state`. The clock, the schedule view and the live places all ask this one rule."""
    state = idle_state(step, definition, stage, takes)
    return state[1] if state else None


def first_sighting(s: ScheduleRow) -> bool:
    """The rule differs from the one the last slot was counted against, or the clock has not seen it live since it
    was saved or last idle. A null last slot alone is not one: a rule whose first slot was ahead when it was seen."""
    return s.rule_digest != digest(s.rule) or s.seen_at is None


def saved_before_slot(s: ScheduleRow, slot: datetime | None, now: datetime) -> bool:
    """A rule saved or changed before its slot that this pass is the first to see: that slot is the rule's own first
    one, so it runs instead of being recorded as seen. A resume or restore (same rule) and a slot found long after it
    passed are not."""
    if slot is None or s.rule_digest == digest(s.rule) or now - slot > LATE_AFTER:
        return False
    if s.rule_digest is not None and s.seen_at is None:
        return (
            False  # seen before and idle since (paused, archived): a resume waits for the next slot, whatever changed
        )
    return datetime.fromisoformat(s.changed_at.replace("Z", "+00:00")) < slot


class ScheduleClock:
    def __init__(
        self,
        db: Any,
        leases: Leases,
        *,
        kinds: ScheduleKinds | None = None,
        handlers: Mapping[str, TargetHandler] | None = None,
    ) -> None:
        """`kinds` are the rule kinds the clock reads rules with, the install's one registry unless a test passes its
        own; `handlers` maps a trigger node type to its target, the workflow start unless a test adds its own."""
        self.db = db
        self.leases = leases
        self.kinds = kinds or KINDS
        runs = RunStore(EngineTransactions(db))
        self.handlers: Mapping[str, TargetHandler] = handlers or {SCHEDULE_TRIGGER: WorkflowStart(runs)}
        self.schedules = WorkflowSchedules(db)
        self.events = TriggerEvents(db)
        self._forgot: dict[str, datetime] = {}

    async def pass_once(self, now: datetime | None = None) -> int:
        """One pass at `now`; returns the runs it started. One schedule's failure never stops the others."""
        now = now or datetime.now(UTC)
        live: dict[str, dict[str, DefinitionRow]] = {}
        for row in await DefinitionStore(EngineTransactions(self.db)).live_everywhere():
            live.setdefault(row.tenant_id, {})[row.workflow_id] = row
        started = 0
        tenants = sorted(set(live) | set(await self.schedules.tenants()))
        for tenant in tenants:
            workflows = live.get(tenant, {})
            with isolation.tenant_wide(SCHEDULE_CLOCK, tenant_id=tenant):
                for s in await self.schedules.everything():
                    definition = workflows.get(s.workflow_id)
                    try:
                        if definition is None or idle_reason(
                            s.trigger_step, definition.definition, definition.stage, self._takes
                        ):
                            # Not live, or the live version lacks the step: idle, and seen afresh when it is back.
                            if s.seen_at is not None:
                                await self.schedules.idle(s.workflow_id, s.trigger_step)
                            continue
                        handler = self._handler(definition, s.trigger_step)
                        assert handler is not None
                        started += await self._one(s, definition, handler, now)
                    except Exception as e:
                        log.exception("schedule_tick_failed", workflow=s.workflow_id, error=type(e).__name__)
        return started

    def _takes(self, node: Json) -> bool:
        return str(node.get("type")) in self.handlers

    def _handler(self, definition: DefinitionRow, step: str) -> TargetHandler | None:
        nodes = cast(list[Json], definition.definition.get("nodes") or [])
        for node in nodes:
            if node.get("id") == step:
                return self.handlers.get(str(node.get("type")))
        return None

    async def _one(self, s: ScheduleRow, definition: DefinitionRow, handler: TargetHandler, now: datetime) -> int:
        seen = self.kinds.last_slot(s.rule, now)
        if not first_sighting(s) and (seen is None or (s.last_slot_at is not None and iso(seen) <= s.last_slot_at)):
            return 0  # nothing new: no slot yet, or this one counted; the lease is for a slot still to count
        lease = lease_key(definition.tenant_id, s.workflow_id, s.trigger_step)
        try:
            await self.leases.acquire(lease, KEY)
        except LeaseHeldError:
            return 0  # another machine has this schedule this minute; the slot stays open
        try:
            # Read again under the lease: the row read before it may be another machine's outcome behind.
            fresh = await self.schedules.get(s.workflow_id, s.trigger_step)
            if fresh is None:
                return 0
            # The slot is read from the row as it is now: a rule changed since the first read is judged as itself.
            return await self._tick(fresh, definition, handler, slot=self.kinds.last_slot(fresh.rule, now), now=now)
        finally:
            await self.leases.release(lease, KEY)

    async def _tick(
        self, s: ScheduleRow, definition: DefinitionRow, handler: TargetHandler, *, slot: datetime | None, now: datetime
    ) -> int:
        rule_digest, at = digest(s.rule), iso(now)
        key = (s.workflow_id, s.trigger_step)
        if first_sighting(s) and not saved_before_slot(s, slot, now):
            if slot is None:
                await self.schedules.sighted(*key, expected=s.last_slot_at, digest=rule_digest, at=at)
            else:
                await self.schedules.record_slot(
                    *key,
                    expected=s.last_slot_at,
                    slot=iso(slot),
                    outcome="seen",
                    digest=rule_digest,
                    run_id=s.last_run_id,
                    at=at,
                )
            return 0
        if slot is None or (s.last_slot_at is not None and iso(slot) <= s.last_slot_at):
            return 0

        async def record(outcome: str, run_id: str | None = None) -> bool:
            # A slot that started nothing keeps the last run's id: that run is what the next tick asks about.
            return await self.schedules.record_slot(
                *key,
                expected=s.last_slot_at,
                slot=iso(slot),
                outcome=outcome,
                digest=rule_digest,
                run_id=run_id or s.last_run_id,
                at=s.seen_at or at,
            )

        await self._forget_old(s, now)
        tick = Tick(s, definition, slot)
        upcoming = self.kinds.next_slots(s.rule, slot, 1)
        before = self.kinds.last_slot(s.rule, slot - timedelta(seconds=1))
        # Missed past half the smaller gap to the slot before or after, so a weekday rule's Friday slot is not caught
        # up on Saturday evening; never within LATE_AFTER: a pass lands up to EVERY_S after its slot, which for a
        # one-minute rule is already past half, and that is a normal pass, not an outage.
        gaps = [g for g in (upcoming[0] - slot if upcoming else None, slot - before if before else None) if g]
        if gaps and now - slot > max(min(gaps) / 2, LATE_AFTER):
            if await record("missed"):
                await self._log(
                    tick,
                    "missed",
                    reason="The clock was down past half the gap to the neighbouring slot, so this slot did not run.",
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
                event_key=slot_key(tick.schedule.workflow_id, tick.slot),
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
