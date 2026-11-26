"""How a saved schedule reads on every surface: the rule, its words and next runs from the server, who changed it last
and how its last slot went. The schedule routes, the workflow view and the agent's live places all answer with it, so
the panel, the lists and the CLI say the same thing."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from ops_engine.node_types import TypeRegistry
from ops_engine.store import DefinitionRow
from ops_service_kit.http import Json, Out
from ops_store.schedule import KINDS

from ..store.schedules import ScheduleRow
from ..store.trigger_events import TriggerEvents
from .schedule_clock import IdleCode, idle_state, iso, slot_key

NEXT_RUNS = 3


class ScheduleView(Out):
    workflow_id: str
    trigger_step: str
    rule: Json
    words: str
    next_runs: list[str]
    changed_by: str
    # The name the saver had when saving, kept as written; empty for a schedule saved before names were kept.
    changed_by_name: str = ""
    changed_at: str
    last_slot_at: str | None = None
    last_outcome: str | None = None
    # Why the schedule starts nothing now, in words; None while it ticks. Shown beside the rule, so a schedule whose
    # step a newer version dropped is never listed as if it ran.
    idle: str | None = None
    # The branch `idle` took, for a screen to pick its alert by; None while the schedule ticks.
    idle_code: IdleCode | None = None
    # The clock's reason for the last slot when it did not run (skipped, refused, missed); None after retention.
    last_outcome_reason: str | None = None
    last_run_id: str | None = None


def next_runs(rule: Json, now: datetime, n: int = NEXT_RUNS) -> list[str]:
    return [iso(t) for t in KINDS.next_slots(rule, now, n)]


def schedulable(registry: TypeRegistry, node: Json) -> bool:
    """Whether the node's type is a trigger a schedule may start (a node type the registry marks schedulable)."""
    found = registry.find(str(node.get("type")), int(cast(int, node.get("typeVersion") or 1)))
    return found is not None and found.schedulable


def idle(row: ScheduleRow, serving: DefinitionRow | None, registry: TypeRegistry) -> tuple[IdleCode, str] | None:
    """Why the saved schedule ticks nothing, given the version that serves the workflow (live or paused)."""

    def takes(node: Json) -> bool:
        return schedulable(registry, node)

    if serving is None:
        return idle_state(row.trigger_step, None, None, takes)
    return idle_state(row.trigger_step, serving.definition, serving.stage, takes)


def schedule_view(
    row: ScheduleRow,
    now: datetime,
    serving: DefinitionRow | None,
    registry: TypeRegistry,
    reasons: dict[tuple[str, str], str] | None = None,
) -> Json:
    """`serving` is the version that serves the workflow (live or paused), None when there is none; `reasons` are the
    clock's reasons by slot key, read for all of a workflow's schedules at once (`schedule_views`)."""
    state = idle(row, serving, registry)
    reason = None
    key = (row.trigger_step, slot_key(row.workflow_id, row.last_slot_at)) if row.last_slot_at else None
    if key and row.last_outcome not in (None, "ran", "seen"):
        reason = (reasons or {}).get(key)
    return ScheduleView(
        workflow_id=row.workflow_id,
        trigger_step=row.trigger_step,
        rule=row.rule,
        words=KINDS.words(row.rule),
        next_runs=next_runs(row.rule, now),
        changed_by=row.changed_by,
        changed_by_name=row.changed_by_name or "",
        changed_at=row.changed_at,
        last_slot_at=row.last_slot_at,
        last_outcome=row.last_outcome,
        idle=state[1] if state else None,
        idle_code=state[0] if state else None,
        last_outcome_reason=reason,
        last_run_id=row.last_run_id,
    ).model_dump(mode="json", by_alias=True)


async def schedule_views(
    db: Any, rows: list[ScheduleRow], now: datetime, serving: DefinitionRow | None, registry: TypeRegistry
) -> list[Json]:
    """The views of a workflow's schedules, with the clock's reasons read in one statement."""
    asked = [(r.trigger_step, slot_key(r.workflow_id, r.last_slot_at)) for r in rows if r.last_slot_at]
    reasons = await TriggerEvents(db).schedule_reasons(rows[0].workflow_id, asked) if rows else {}
    return [schedule_view(r, now, serving, registry, reasons) for r in rows]
