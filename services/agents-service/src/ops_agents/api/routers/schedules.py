"""Saved schedules on a workflow's trigger step, and the rule kinds they are written in.

A schedule is saved outside the workflow's versions (store/schedules.py), so a save applies at once to whatever version
is live, with no publish. Saving or clearing one needs the right to pause the workflow and the right an email trigger
asks to go live (`deployments.create`): both put a workflow to work with no person in it. A workflow no team owns
cannot carry one, since its runs would have no team. Each schedule is read and written through its workflow's rights;
the schedules table is tenant-scoped with the team as a plain column, because shared workflows have no team.

The words and the next runs come from the server, so the panel, the lists and the CLI say the same thing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ops_access import can
from ops_identity.fastapi import Tx
from ops_service_kit.errors import NotFound, Unprocessable
from ops_service_kit.http import Envelope, In, Json, JsonValue
from ops_service_kit.logging import get_logger
from ops_store.schedule import InvalidSchedule, ScheduleKinds, UnknownKind, default_kinds

from ...store.schedules import ScheduleRow, WorkflowSchedules
from ...store.tenancy import current_team
from .. import engine_lifecycle
from ..auth import caller_of, principal
from ..deps import Runtime
from ..envelope import ok
from ..schedule_clock import SCHEDULE_TRIGGER, iso
from ..schemas import Out  # pyright: ignore[reportPrivateImportUsage]
from .engine import Me, Rt, definitions

log = get_logger("ops_agents.api.routers.schedules")
router = APIRouter(prefix="/v1/schedules", dependencies=[Depends(principal)])
workflow_router = APIRouter(prefix="/v1/workflows", dependencies=[Depends(principal)])

KINDS: ScheduleKinds = default_kinds()
# The trigger node types a schedule may be saved on: each one's runs get `dueAt` from the clock.
SCHEDULABLE = frozenset({SCHEDULE_TRIGGER})
# The one input field the clock fills.
CLOCK_FIELDS = frozenset({"dueAt"})
NEXT_RUNS = 3


class KindView(Out):
    name: str
    label: str
    schema_: Json = Field(alias="schema")


class RuleIn(In):
    rule: dict[str, JsonValue]


class PreviewView(Out):
    rule: Json
    words: str
    next_runs: list[str]


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


def floor(rt: Runtime) -> timedelta:
    return timedelta(minutes=rt.settings.schedule_floor_minutes)


def checked(rt: Runtime, raw: dict[str, JsonValue], now: datetime) -> Json:
    try:
        return KINDS.checked(raw, now, floor(rt))
    except UnknownKind as e:
        raise Unprocessable(
            str(e), code="schedule_kind_unknown", details={"field": e.field, "known": list(e.known)}
        ) from e
    except InvalidSchedule as e:
        raise Unprocessable(str(e), code="schedule_invalid", details={"field": e.field}) from e


def preview(rule: Json, now: datetime) -> dict[str, Any]:
    upcoming = [iso(t) for t in KINDS.next_slots(rule, now, NEXT_RUNS)]
    return PreviewView(rule=rule, words=KINDS.words(rule), next_runs=upcoming).model_dump(mode="json", by_alias=True)


def view(row: ScheduleRow, now: datetime) -> dict[str, Any]:
    return ScheduleView(
        workflow_id=row.workflow_id,
        trigger_step=row.trigger_step,
        rule=row.rule,
        words=KINDS.words(row.rule),
        next_runs=[iso(t) for t in KINDS.next_slots(row.rule, now, NEXT_RUNS)],
        changed_by=row.changed_by,
        changed_at=row.changed_at,
        last_slot_at=row.last_slot_at,
        last_outcome=row.last_outcome,
    ).model_dump(mode="json", by_alias=True)


@router.get("/kinds", response_model=Envelope[list[KindView]])
async def schedule_kinds(me: Me) -> JSONResponse:
    """Every rule kind a schedule may be written in, with its label and the JSON Schema of its own fields."""
    return ok([{"name": k.name, "label": k.label, "schema": k.schema} for k in KINDS.all()])


@router.post("/preview", response_model=Envelope[PreviewView])
async def preview_schedule(rt: Rt, me: Me, body: RuleIn) -> JSONResponse:
    """The rule as it would be saved, in words, with its next three runs. 422 naming the field for a rule a save would
    refuse, including one under the install's shortest interval."""
    now = datetime.now(UTC)
    return ok(preview(checked(rt, body.rule, now), now))


async def _workflow(rt: Runtime, me: Any, workflow_id: str, step: str, *, writing: bool) -> Any:
    """The workflow's current row, after the rights a schedule needs; 404 when the caller sees no such workflow or
    the step is not a schedulable trigger of its live or working version."""
    store = definitions(rt)
    row = await store.row(workflow_id, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    if writing:
        engine_lifecycle.require_rights(me, row, "pause")
        if not row.team_id:
            raise Unprocessable(
                "A scheduled run needs a team, and this workflow belongs to none.",
                code="schedule_needs_team",
                details={"field": "team"},
            )
        can(caller_of(me), "deployments", "create", team=row.team_id, what="a schedule on this workflow")
    # The live version, the latest saved one and the editor's working copy: a schedule applies to whichever goes live.
    live = await store.live(workflow_id, team=current_team())
    working = await store.working_copy(workflow_id, team=current_team())
    versions = [v.definition for v in (live, row, working) if v]
    steps = [n for d in versions for n in cast(list[Json], d.get("nodes") or []) if n.get("id") == step]
    if not steps or any(str(n.get("type")) not in SCHEDULABLE for n in steps):
        raise NotFound(f"Schedule trigger {step} on {workflow_id}")
    for n in steps if writing else []:
        schema = cast(Json, cast(Json, n.get("parameters") or {}).get("inputSchema") or {})
        if extra := sorted(set(cast(list[str], schema.get("required") or [])) - CLOCK_FIELDS):
            raise Unprocessable(
                f"A scheduled run sends only dueAt, and this trigger's input schema requires {extra[0]}.",
                code="schedule_input_required",
                details={"field": extra[0]},
            )
    return row


@workflow_router.get("/definitions/{workflow_id}/triggers/{step}/schedule", response_model=Envelope[ScheduleView])
async def get_schedule(rt: Rt, me: Me, workflow_id: str, step: str) -> JSONResponse:
    """The schedule saved on the trigger step, in words, with its next runs and last outcome; 404 when none is saved."""
    await _workflow(rt, me, workflow_id, step, writing=False)
    row = await WorkflowSchedules(rt.db).get(workflow_id, step)
    if row is None:
        raise NotFound(f"No schedule on {step} of {workflow_id}")
    return ok(view(row, datetime.now(UTC)))


@workflow_router.put("/definitions/{workflow_id}/triggers/{step}/schedule", response_model=Envelope[ScheduleView])
async def save_schedule(rt: Rt, me: Me, _: Tx, workflow_id: str, step: str, body: RuleIn) -> JSONResponse:
    """Saves the schedule; it applies at once to the live version, with no publish, and first runs at its next slot.
    403 without the rights to pause the workflow and put it on a channel; 422 naming the field for a bad rule, a rule
    under the shortest interval, an input schema that needs more than dueAt, or a workflow with no team."""
    now = datetime.now(UTC)
    wf = await _workflow(rt, me, workflow_id, step, writing=True)
    rule = checked(rt, body.rule, now)
    store = WorkflowSchedules(rt.db)
    before = await store.save(workflow_id, step, wf.team_id, rule, me.sub)
    log.info(
        "schedule_saved",
        workflow=workflow_id,
        step=step,
        by=me.sub,
        before=KINDS.words(before) if before else None,
        after=KINDS.words(rule),
    )
    row = await store.get(workflow_id, step)
    assert row is not None
    return ok(view(row, now))


@workflow_router.delete("/definitions/{workflow_id}/triggers/{step}/schedule", status_code=204, response_model=None)
async def clear_schedule(rt: Rt, me: Me, _: Tx, workflow_id: str, step: str) -> Response:
    """Clears the schedule: nothing more ticks. 404 when none was saved."""
    await _workflow(rt, me, workflow_id, step, writing=True)
    store = WorkflowSchedules(rt.db)
    before = await store.get(workflow_id, step)
    if before is None or not await store.clear(workflow_id, step):
        raise NotFound(f"No schedule on {step} of {workflow_id}")
    log.info("schedule_cleared", workflow=workflow_id, step=step, by=me.sub, before=KINDS.words(before.rule))
    return Response(status_code=204)
