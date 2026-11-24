"""How a saved schedule reads on every surface: the rule, its words and next runs from the server, who changed it last
and how its last slot went. The schedule routes, the workflow view and the agent's live places all answer with it, so
the panel, the lists and the CLI say the same thing."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from ops_engine.node_types import TypeRegistry
from ops_engine.store import DefinitionRow
from ops_service_kit.http import Json, Out
from ops_store.schedule import KINDS

from ..store.schedules import ScheduleRow
from .schedule_clock import idle_reason, iso

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
    # Why the schedule starts nothing now, in words; None while it ticks. Shown beside the rule, so a schedule whose
    # step a newer version dropped is never listed as if it ran.
    idle: str | None = None


def next_runs(rule: Json, now: datetime, n: int = NEXT_RUNS) -> list[str]:
    return [iso(t) for t in KINDS.next_slots(rule, now, n)]


def schedulable(registry: TypeRegistry, node: Json) -> bool:
    """Whether the node's type is a trigger a schedule may start (a node type the registry marks schedulable)."""
    found = registry.find(str(node.get("type")), int(cast(int, node.get("typeVersion") or 1)))
    return found is not None and found.schedulable


def idle(row: ScheduleRow, serving: DefinitionRow | None, registry: TypeRegistry) -> str | None:
    """Why the saved schedule ticks nothing, given the version that serves the workflow (live or paused)."""

    def takes(node: Json) -> bool:
        return schedulable(registry, node)

    if serving is None:
        return idle_reason(row.trigger_step, None, None, takes)
    return idle_reason(row.trigger_step, serving.definition, serving.stage, takes)


def schedule_view(row: ScheduleRow, now: datetime, serving: DefinitionRow | None, registry: TypeRegistry) -> Json:
    """`serving` is the version that serves the workflow (live or paused), None when there is none."""
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
        idle=idle(row, serving, registry),
    ).model_dump(mode="json", by_alias=True)
