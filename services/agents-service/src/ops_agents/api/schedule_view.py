"""How a saved schedule reads on every surface: the rule, its words and next runs from the server, who changed it last
and how its last slot went. The schedule routes, the workflow view and the agent's live places all answer with it, so
the panel, the lists and the CLI say the same thing."""

from __future__ import annotations

from datetime import datetime

from ops_service_kit.http import Json, Out
from ops_store.schedule import KINDS

from ..store.schedules import ScheduleRow
from .schedule_clock import iso

NEXT_RUNS = 3


class ScheduleView(Out):
    workflow_id: str
    trigger_step: str
    rule: Json
    words: str
    next_runs: list[str]
    changed_by: str
    changed_at: str
    last_slot_at: str | None = None
    last_outcome: str | None = None


def next_runs(rule: Json, now: datetime, n: int = NEXT_RUNS) -> list[str]:
    return [iso(t) for t in KINDS.next_slots(rule, now, n)]


def schedule_view(row: ScheduleRow, now: datetime) -> Json:
    return ScheduleView(
        workflow_id=row.workflow_id,
        trigger_step=row.trigger_step,
        rule=row.rule,
        words=KINDS.words(row.rule),
        next_runs=next_runs(row.rule, now),
        changed_by=row.changed_by,
        changed_at=row.changed_at,
        last_slot_at=row.last_slot_at,
        last_outcome=row.last_outcome,
    ).model_dump(mode="json", by_alias=True)
