"""`/v1/tasks`: a Human Task an API caller posts with a task type and its values (c-288).

A posted task is recorded as a `task.requested` event of this service and runs as the api_task system workflow, so it
lists, times out, is assigned and is audited as every other task, with no second queue. The task id is that run's id.
Posting one starts a run (`workflows.run` in the acting team); the caller reads the decision back from the task.

A missing required value is accepted with a warning and the screen shows its fallback; a value of the wrong kind is
refused with 422 naming the field, since no fallback can show it (owner, 2026-10-18)."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_access import can
from ops_contracts.chat import WireModel
from ops_engine.compiler import DEFAULT_OPTIONS
from ops_engine.store import RunStore
from ops_service_kit.errors import Unprocessable
from ops_service_kit.http import Envelope
from ops_service_kit.ids import new_id

from ... import task_types as tt
from ...store.engine import EngineTransactions
from ...store.tenancy import current_team
from .. import engine_reviews, service_events
from ..auth import Principal, caller_in, caller_of, started_by
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import Out, TaskWarning
from ..task_type_seeds import task_type_store

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(caller_in("workflows"))]  # noqa: UP040

router = APIRouter(prefix="/v1/tasks")
EVENT = "task.requested"
# How long a post waits for its task to open before answering `starting`.
OPEN_WAIT_SECONDS = 5.0
SOURCE = "agents"


class TaskIn(WireModel):
    type: str = Field(min_length=1, max_length=64)
    # The version to open; the newest published one when empty, kept on the task either way.
    version: int | None = Field(default=None, ge=1)
    params: dict[str, Any] = Field(default_factory=dict[str, Any])


class TaskCreated(Out):
    id: str
    # The console page that opens it.
    url: str
    # waiting: the task is open now and its page answers; starting: the worker has not reached the step yet.
    status: Literal["waiting", "starting"]
    type: str
    version: int
    warnings: list[TaskWarning]


class TaskState(Out):
    id: str
    status: str
    # The action a person chose (the step's out port), the reason they gave and who decided; None while pending.
    action: str | None
    reason: str | None
    decided_by: str | None
    decided_at: str | None
    # Values the decision carried: a reviewer's corrections or an action's inputs.
    values: dict[str, Any] | None


async def _opened(rt: Runtime, run_id: str) -> Literal["waiting", "starting"]:
    """Waits up to OPEN_WAIT_SECONDS for the worker to reach the task's step, so a caller can open the task's page at
    once (its URL answers only once the run waits there)."""
    runs = RunStore(EngineTransactions(rt.db))
    deadline = asyncio.get_running_loop().time() + OPEN_WAIT_SECONDS
    while True:
        run = await runs.get(run_id)
        if run is not None and run["status"] == "waiting":
            return "waiting"
        if asyncio.get_running_loop().time() >= deadline:
            return "starting"
        await asyncio.sleep(0.2)


def _team(me: Principal) -> str:
    team = current_team() or me.team_id
    if not team:
        raise Unprocessable(
            "Choose a team with the X-Team-Id header; a task belongs to one team.", code="team_required"
        )
    return team


@router.post("", response_model=Envelope[TaskCreated], status_code=201)
async def create_task(
    rt: Rt,
    me: Me,
    body: TaskIn,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=200)] = None,
) -> JSONResponse:
    """Opens a task of a type for a person to decide in Human Tasks; 422 when a value is of the wrong kind. A post
    repeated with the same Idempotency-Key, by the same caller, answers with the task the first one opened."""
    team = _team(me)
    can(caller_of(me), "workflows", "run", team=team, what="a task")
    version, record = await (await task_type_store(rt)).published(body.type, body.version)
    issues = tt.check_params(record, body.params)
    wrong = [i for i in issues if i["severity"] == "error"]
    if wrong:
        raise Unprocessable(
            "; ".join(i["message"] for i in wrong),
            code="invalid_task_params",
            details={"fields": [i["field"] for i in wrong]},
        )
    event = await service_events.emit(
        rt,
        name=EVENT,
        # The event key: a repeated key returns the run it started (service_events), so a retry opens no second task.
        # Prefixed with the caller, so two callers' keys never meet.
        key=f"{started_by(me)}:{idempotency_key}" if idempotency_key else new_id("task"),
        team_id=team,
        source=SOURCE,
        actor=me.email or None,
        payload={"taskType": {"id": body.type, "version": version}, "params": body.params},
    )
    run_ids = cast(list[str], event["run_ids"])
    if not run_ids:
        raise Unprocessable("No workflow handles posted tasks in this workspace.", code="task_unhandled")
    status = await _opened(rt, run_ids[0])
    created = TaskCreated(
        id=run_ids[0],
        url=f"/reviews/{run_ids[0]}",
        status=status,
        type=body.type,
        version=version,
        warnings=[TaskWarning(**w) for w in issues],
    )
    return ok(created.model_dump(mode="json", by_alias=True), 201)


def _action(review: dict[str, Any], resume: dict[str, Any]) -> str:
    """The out port the decision left by, as the review step reads it: the option chosen, else Approve or Reject."""
    option = review.get("option") or resume.get("option")
    return str(option or DEFAULT_OPTIONS.get(str(resume.get("decision")), resume.get("decision")))


@router.get("/{task_id}", response_model=Envelope[TaskState])
async def get_task(rt: Rt, me: Me, task_id: str) -> JSONResponse:
    """The task's status and, once decided, the action, reason, values and decider."""
    review = await engine_reviews.get(rt, task_id)
    resume = cast(dict[str, Any] | None, review.get("resume")) or {}
    decided = review.get("status") not in ("pending", "in_review")
    state = TaskState(
        id=task_id,
        status=str(review["status"]),
        action=_action(review, resume) if decided else None,
        reason=cast(str | None, review.get("decisionReason")),
        decided_by=cast(str | None, review.get("decidedBy")),
        decided_at=cast(str | None, review.get("decidedAt")),
        values=cast(dict[str, Any] | None, resume.get("edited") or resume.get("values")) if decided else None,
    )
    return ok(state.model_dump(mode="json", by_alias=True))
