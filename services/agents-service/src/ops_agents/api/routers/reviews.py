"""The review service's decide path: each approver approves the exact call a paused thread is waiting to make, and
once enough people have, the response carries an approval token bound to that call. The client resumes the thread
with the token in its decision, so it lands in the checkpoint and a resume after a restart still has it.

The call comes from the interrupt (`payload.call = {tool, input, step}`), the call the node will make on resume, so
the token is bound to what will run, not to a summary of it.
"""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ops_contracts.chat import WireModel
from ops_policy import input_hash
from ops_policy.approval import Binding, mint_approval
from ops_service_kit.errors import ApiError, Conflict, Forbidden, NotFound
from ops_service_kit.http import Envelope

from ...store.review_assignments import ReviewAssignments
from ...store.reviews import ReviewStore
from ...store.service_events import attempts_of
from .. import hitl_facade, service_events
from ..auth import (
    Principal,
    principal,
    require_not_own,
    require_reviews_decide,
    require_step_up,
    review_teams,
    workspace_step_up,
)
from ..deps import Runtime, runtime
from ..envelope import ok
from ..runs import config, graph_store, pending, resolve
from ..schemas import Approval, BulkResult, Out, Review, ReviewList
from ..tool_access import one_read_per_tool, policy_of

router = APIRouter(prefix="/v1/threads", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040


class ApprovalInput(WireModel):
    step_up_token: str | None = None


@router.post("/{thread_id}/approvals", response_model=Envelope[Approval])
async def approve(rt: Rt, me: Me, thread_id: str, body: ApprovalInput) -> JSONResponse:
    return ok(await record_approval(rt, me, thread_id, body.step_up_token))


async def record_approval(
    rt: Runtime,
    approver: Principal,
    thread_id: str,
    step_up_token: str | None,
    *,
    call: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Records `approver`'s approval of the call the thread waits on; the token is set once as many distinct people as
    the operation's policy names have approved. `call` is the one a decision chose when the step offers options (a
    levy review's hold or flag); else the payload's `call`."""
    row, graph = await resolve(rt, thread_id)
    waiting = pending(await graph.aget_state(config(thread_id)))
    if call is None:
        call = waiting[0]["payload"].get("call") if waiting else None
    if call is None:
        raise Conflict("This thread is not waiting on a call to approve.", code="nothing_to_approve")
    teams = review_teams(approver)
    policy = await policy_of(rt, call["tool"])
    hitl_facade.require_approver_team(policy, teams, call["tool"])
    if not policy.approver_team:
        # No approving team named: the thread's team reviews it, by its reviewers and admins (c-122 Q3).
        require_reviews_decide(teams, str(row["team_id"]), f"the write {call['tool']}")
    payload: dict[str, Any] = waiting[0]["payload"] if waiting else {}
    require_not_own(
        approver,
        [hitl_facade.requester_of(row, payload)],
        team=policy.approver_team or str(row["team_id"]),
        what=f"the write {call['tool']}",
    )
    if policy.approvers > 1 or workspace_step_up(approver):
        require_step_up(rt, approver.email, step_up_token)
    digest = input_hash(call["input"])
    # Two approvers means two people: approving the same input again does not count as the second. Only approvals
    # of this exact input count: an approval of an earlier draft of the call is not one of these.
    found = await ReviewStore(graph_store(rt).engine).approve(
        thread_id, call["step"], approver.email, digest, distinct=policy.approvers > 1
    )
    if found is None:
        raise Forbidden("You already approved this; a second, different person has to approve it.")
    approvers = found
    needed = policy.approvers
    token = (
        mint_approval(
            Binding(thread_id, call["step"], call["tool"], digest, approvers),
            rt.settings.review_key.get_secret_value(),
            ttl_s=rt.settings.review_token_ttl_seconds,
        )
        if len(approvers) >= needed
        else None
    )
    return {"approvers": approvers, "needed": needed, "inputHash": digest, "approvalToken": token}


# The console's Reviews routes (see hitl_facade): runtime review steps as `Review` rows, and decide-then-resume.
console_router = APIRouter(prefix="/reviews", dependencies=[Depends(principal)])


class ReviewDecisionInput(WireModel):
    """The console's `ReviewDecisionInput`. Conditions, acting-as and test cases apply to other review kinds and are
    accepted and ignored here, so one decide call serves every kind."""

    decision: str
    reason: str | None = None
    step_up_token: str | None = None
    # A step with options: the inputs the reviewer set, validated against the option's declaration (c-057);
    # `amount` is the console's shorthand for the one input so named.
    inputs: dict[str, Any] | None = None
    amount: float | None = None
    conditions: list[dict[str, Any]] | None = None
    acting_as_id: str | None = None
    add_test_case: bool | None = None


class ReviewsQuery(BaseModel):
    view: str = "open"
    page: int = 1
    pageSize: int = 25  # noqa: N815 - the console's query parameter
    search: str | None = None
    risk: list[str] = Field(default_factory=list[str])
    workflowId: list[str] = Field(default_factory=list[str])  # noqa: N815
    kind: list[str] = Field(default_factory=list[str])
    agentSlug: list[str] = Field(default_factory=list[str])  # noqa: N815
    status: list[str] = Field(default_factory=list[str])


@console_router.get("", response_model=Envelope[ReviewList])
async def list_reviews(rt: Rt, me: Me, q: Annotated[ReviewsQuery, Query()]) -> JSONResponse:
    filters = {"risk": q.risk, "workflowId": q.workflowId, "kind": q.kind, "agentSlug": q.agentSlug, "status": q.status}
    with one_read_per_tool():
        rows = await hitl_facade.list_reviews(
            rt,
            view=q.view,
            filters=filters,
            search=q.search,
            page_no=q.page,
            size=q.pageSize,
            me=frozenset({me.email, me.name}),
        )
        rows["data"] = [await _with_can_decide(rt, me, r) for r in rows["data"]]
    return ok(rows)


async def _with_can_decide(rt: Runtime, me: Principal, review: dict[str, Any]) -> dict[str, Any]:
    """The review with whether the caller may decide it now (c-123): the console shows Approve and Reject only then."""
    waiting = review.get("status") in ("pending", "in_review")
    return review | {"canDecide": waiting and await hitl_facade.can_decide(rt, me, str(review["id"]))}


@console_router.get("/by-run-key/{run_key:path}", response_model=Envelope[Review])
async def get_review_by_run_key(rt: Rt, me: Me, run_key: str) -> JSONResponse:
    """The review of the run a service event started in its handler (c-257), by its run key `<event>:<key>`: the step
    it waits on, else its latest decision. A service links to it before the run exists, so it names the key, not the
    step; a team that cannot see the run gets not found, as for the step itself."""
    event = run_key.split(":", 1)[0]
    handler = service_events.handler_ids(rt).get(event)
    runs = await attempts_of(rt.db, handler, run_key) if handler else []
    if not runs:
        raise NotFound("Review")
    latest = max(runs, key=lambda r: (r["created_at"], r["run_key"]))
    review = await hitl_facade.with_assignee(rt, await hitl_facade.get_review(rt, str(latest["id"])))
    return ok(await _with_can_decide(rt, me, review))


class QueuePlace(Out):
    # None when the review is not in the view (decided, or filtered out); total is the view's size either way.
    position: int | None
    total: int
    previous: str | None
    next: str | None


@console_router.get("/{review_id}/place", response_model=Envelope[QueuePlace])
async def get_queue_place(rt: Rt, me: Me, review_id: str, view: str = "open") -> JSONResponse:
    """Where the review sits in a Human Tasks view (open by default): position, total and the reviews either side."""
    with one_read_per_tool():
        return ok(await hitl_facade.queue_place(rt, review_id, view))


@console_router.get("/{thread_id}", response_model=Envelope[Review])
async def get_review(rt: Rt, me: Me, thread_id: str) -> JSONResponse:
    review = await hitl_facade.with_assignee(rt, await hitl_facade.get_review(rt, thread_id))
    return ok(await _with_can_decide(rt, me, review))


@console_router.post("/{thread_id}/decision", response_model=Envelope[Review])
async def decide(rt: Rt, me: Me, thread_id: str, body: ReviewDecisionInput) -> JSONResponse:
    review = await hitl_facade.decide(
        rt,
        me,
        thread_id,
        decision=body.decision,
        reason=body.reason or None,
        step_up_token=body.step_up_token,
        amount=body.amount,
        inputs=body.inputs,
    )
    return ok(review)


class BulkDecisionInput(WireModel):
    ids: list[str]
    decision: str
    reason: str | None = None
    step_up_token: str | None = None


class AssignInput(WireModel):
    ids: list[str] = Field(min_length=1, max_length=200)
    # A person's email; the caller when left out (Assign to me).
    assignee: str | None = Field(default=None, min_length=3, max_length=320)


@console_router.post("/bulk-decision", response_model=Envelope[BulkResult])
async def bulk_decide(rt: Rt, me: Me, body: BulkDecisionInput) -> JSONResponse:
    updated: list[str] = []
    skipped: list[dict[str, str]] = []
    for thread_id in body.ids:
        try:
            await hitl_facade.decide(
                rt,
                me,
                thread_id,
                decision=body.decision,
                reason=body.reason,
                step_up_token=body.step_up_token,
            )
            updated.append(thread_id)
        except ApiError as e:
            skipped.append({"id": thread_id, "reason": e.message})
    return ok({"updated": updated, "skipped": skipped})


@console_router.post("/assign", response_model=Envelope[BulkResult])
async def assign(rt: Rt, me: Me, body: AssignInput) -> JSONResponse:
    """Assigns each open review to `assignee`, the caller when left out (c-074). Only someone who may decide a review
    assigns it; assigning routes the review and changes nothing about who may decide it. A result per id."""
    to = (body.assignee or me.email).strip()
    updated: list[str] = []
    skipped: list[dict[str, str]] = []
    for review_id in body.ids:
        try:
            review = await hitl_facade.get_review(rt, review_id)
        except ApiError as e:
            skipped.append({"id": review_id, "reason": e.message})
            continue
        if review.get("status") not in ("pending", "in_review"):
            skipped.append({"id": review_id, "reason": "It is already decided."})
        elif not await hitl_facade.can_decide(rt, me, review_id):
            skipped.append({"id": review_id, "reason": "Only someone who may decide it assigns it."})
        else:
            await ReviewAssignments(rt.db).assign(str(review["id"]), to, by=me.email)
            updated.append(review_id)
    return ok({"updated": updated, "skipped": skipped})
