"""Saved schedules on a workflow's trigger step, and the rule kinds they are written in.

A schedule is saved outside the workflow's versions (store/schedules.py), so a save applies at once to whatever version
is live, with no publish. Saving or clearing one needs the right to pause the workflow and the right an email trigger
asks to go live (`deployments.create`): both put a workflow to work with no person in it. A workflow no team owns
cannot carry one, since its runs would have no team. Reading one needs the right to view the team's workflows; clearing
one needs the save's rights and nothing else, so a schedule whose step is gone can still be cleared. The floor is
checked at each save only: raising it leaves saved schedules running, and each is refused at its next save. The
schedules table is team-owned (store/schedules.py): these routes read the acting team's schedules, and a workflow no
team owns has none, since a save on one is refused.

The words and the next runs come from the server, so the panel, the lists and the CLI say the same thing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ops_access import can
from ops_engine.store import DefinitionRow
from ops_identity.fastapi import Tx
from ops_service_kit.errors import NotFound, Unprocessable
from ops_service_kit.http import Envelope, In, Json, JsonValue, OptionsPage, options_page, options_window
from ops_service_kit.logging import get_logger
from ops_store.schedule import KINDS, InvalidSchedule, UnknownKind

from ...store.schedules import WorkflowSchedules
from ...store.tenancy import current_team
from .. import engine_lifecycle
from ..auth import caller_of, principal
from ..deps import Runtime
from ..envelope import ok
from ..schedule_audit import entry
from ..schedule_clock import required_beyond_due
from ..schedule_view import ScheduleView, next_runs, schedulable, schedule_views
from ..schemas import Out  # pyright: ignore[reportPrivateImportUsage]
from .engine import REGISTRY, Me, Reader, Rt, definitions
from .tool_catalog import options_cut

log = get_logger("ops_agents.api.routers.schedules")
router = APIRouter(prefix="/v1/schedules", dependencies=[Depends(principal)])
workflow_router = APIRouter(prefix="/v1/workflows", dependencies=[Depends(principal)])


class KindView(Out):
    name: str
    label: str
    schema_: Json = Field(alias="schema")


class RuleIn(In):
    rule: dict[str, JsonValue]


class PreviewIn(RuleIn):
    # The instant the next runs are counted from, now when left out: how a rule reads across a day the clocks change.
    after: datetime | None = None


class PreviewView(Out):
    rule: Json
    words: str
    next_runs: list[str]


def schedule_input_refused(field: str) -> Unprocessable:
    return Unprocessable(
        f"A scheduled run sends only dueAt, and this trigger's input schema requires {field}.",
        code="schedule_input_required",
        details={"field": field},
    )


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


def preview(rule: Json, now: datetime) -> PreviewView:
    return PreviewView(rule=rule, words=KINDS.words(rule), next_runs=next_runs(rule, now))


@router.get("/kinds", response_model=Envelope[list[KindView]])
async def schedule_kinds(me: Me) -> JSONResponse:
    """Every rule kind a schedule may be written in, with its label and the JSON Schema of its own fields."""
    return ok([{"name": k.name, "label": k.label, "schema": k.schema} for k in KINDS.all()])


@router.get("/zones", response_model=Envelope[OptionsPage])
async def schedule_zones(
    me: Me, search: str = "", cursor: str | None = None, limit: Annotated[int, Query(ge=1, le=50)] = 25
) -> JSONResponse:
    """The time zones a rule's `tz` may name, searched by a case-blind part of the name and paged: the same zone data
    the save checks against, so a zone listed here is never refused."""
    q = search.strip().lower()
    zones = [z for z in sorted(available_timezones()) if q in z.lower()]
    offset, _ = options_window(cursor, limit)
    return ok(options_page([{"id": z, "label": z} for z in options_cut(zones, offset, limit)], offset, limit))


@router.post("/preview", response_model=Envelope[PreviewView])
async def preview_schedule(rt: Rt, me: Me, body: PreviewIn) -> JSONResponse:
    """The rule as it would be saved, in words, with its next three runs. 422 naming the field for a rule a save would
    refuse, including one under the install's shortest interval."""
    now = datetime.now(UTC)
    return ok(preview(checked(rt, body.rule, now), body.after or now).model_dump(mode="json", by_alias=True))


async def _rights(rt: Runtime, me: Any, workflow_id: str) -> Any:
    """The workflow's current row after the rights saving or clearing a schedule needs; 404 when the caller sees no
    such workflow."""
    row = await definitions(rt).row(workflow_id, team=current_team())
    if row is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    engine_lifecycle.require_rights(me, row, "pause")
    if row.team_id:
        can(caller_of(me), "deployments", "create", team=row.team_id, what="a schedule on this workflow")
    return row


async def _saveable(rt: Runtime, row: Any, step: str) -> None:
    """What a save needs beyond the rights: a team, and a schedulable trigger `step` in the live version, the latest
    saved one and the editor's working copy, none of them requiring an input the clock cannot fill."""
    if not row.team_id:
        raise Unprocessable(
            "A scheduled run needs a team, and this workflow belongs to none.",
            code="schedule_needs_team",
            details={"field": "team"},
        )
    store, wid = definitions(rt), row.workflow_id
    # A schedule applies to whichever version goes live.
    live = await store.live(wid, team=current_team())
    working = await store.working_copy(wid, team=current_team())
    versions = [v.definition for v in (live, row, working) if v]
    steps = [n for d in versions for n in cast(list[Json], d.get("nodes") or []) if n.get("id") == step]
    if not steps or not all(schedulable(REGISTRY, n) for n in steps):
        raise NotFound(f"Schedule trigger {step} on {wid}")
    for d in versions:
        if field := required_beyond_due(d, step):
            raise schedule_input_refused(field)


async def serving_definition(rt: Runtime, workflow_id: str) -> DefinitionRow | None:
    return await definitions(rt).serving(workflow_id, team=current_team())


@workflow_router.get("/definitions/{workflow_id}/triggers/{step}/schedule", response_model=Envelope[ScheduleView])
async def get_schedule(rt: Rt, me: Reader, workflow_id: str, step: str) -> JSONResponse:
    """The schedule saved on the trigger step, in words, with its next runs, last outcome and why it is idle when it
    is. 403 without the right to view the team's workflows; 404 when none is saved."""
    if await definitions(rt).row(workflow_id, team=current_team()) is None:
        raise NotFound(f"Workflow definition {workflow_id}")
    row = await WorkflowSchedules(rt.db).get(workflow_id, step)
    if row is None:
        raise NotFound(f"The schedule on {step} of {workflow_id}")
    now = datetime.now(UTC)
    return ok((await schedule_views(rt.db, [row], now, await serving_definition(rt, workflow_id), REGISTRY))[0])


@workflow_router.put("/definitions/{workflow_id}/triggers/{step}/schedule", response_model=Envelope[ScheduleView])
async def save_schedule(rt: Rt, me: Me, _: Tx, workflow_id: str, step: str, body: RuleIn) -> JSONResponse:
    """Saves the schedule; it applies at once to the live version, with no publish, and first runs at its next slot.
    403 without the rights to pause the workflow and put it on a channel; 422 naming the field for a bad rule, a rule
    under the shortest interval, an input schema that needs more than dueAt, or a workflow with no team."""
    now = datetime.now(UTC)
    wf = await _rights(rt, me, workflow_id)
    await _saveable(rt, wf, step)
    # The floor is checked here, at each save: a schedule saved before the floor was raised keeps running until then.
    rule = checked(rt, body.rule, now)
    store = WorkflowSchedules(rt.db)
    before = await store.save(workflow_id, step, wf.team_id, rule, me.sub, by_name=me.name or me.email)
    await store.audit(
        team_id=wf.team_id, actor=me.sub, workflow_id=workflow_id, **entry("save", wf.name, step, before, rule)
    )
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
    return ok((await schedule_views(rt.db, [row], now, await serving_definition(rt, workflow_id), REGISTRY))[0])


@workflow_router.delete("/definitions/{workflow_id}/triggers/{step}/schedule", status_code=204, response_model=None)
async def clear_schedule(rt: Rt, me: Me, _: Tx, workflow_id: str, step: str) -> Response:
    """Clears the schedule: nothing more ticks. Needs the same rights as a save and nothing else, so a schedule whose
    step a newer version dropped, or whose newest version needs an input, can still be cleared. 404 when none was
    saved."""
    wf = await _rights(rt, me, workflow_id)
    store = WorkflowSchedules(rt.db)
    before = await store.get(workflow_id, step)
    if before is None or not await store.clear(workflow_id, step):
        raise NotFound(f"The schedule on {step} of {workflow_id}")
    await store.audit(
        team_id=before.team_id,
        actor=me.sub,
        workflow_id=workflow_id,
        **entry("clear", wf.name, step, before.rule, None),
    )
    log.info("schedule_cleared", workflow=workflow_id, step=step, by=me.sub, before=KINDS.words(before.rule))
    return Response(status_code=204)
