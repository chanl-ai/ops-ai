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
from ops_service_kit.errors import ApiError, Conflict, Forbidden

from ...store.reviews import ReviewStore
from .. import hitl_facade
from ..auth import Principal, principal, require_step_up, teams_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..runs import config, graph_store, pending, resolve
from ..schemas import Approval, BulkResult, Envelope, Review, ReviewList
from ..tool_access import policy_of

router = APIRouter(prefix="/v1/threads", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040


class ApprovalInput(WireModel):
    step_up_token: str | None = None


@router.post("/{thread_id}/approvals", response_model=Envelope[Approval])
async def approve(rt: Rt, me: Me, thread_id: str, body: ApprovalInput) -> JSONResponse:
    return ok(await record_approval(rt, me.email, thread_id, body.step_up_token, approver_teams=teams_of(me)))


async def record_approval(
    rt: Runtime,
    approver: str,
    thread_id: str,
    step_up_token: str | None,
    *,
    approver_teams: list[str] | None = None,
) -> dict[str, Any]:
    """Records `approver`'s approval of the call the thread waits on; the token is set once as many distinct people as
    the operation's policy names have approved. `approver_teams` None (dev) approves for any team."""
    row, graph = await resolve(rt, thread_id)
    waiting = pending(await graph.aget_state(config(thread_id)))
    call: dict[str, Any] | None = waiting[0]["payload"].get("call") if waiting else None
    if call is None:
        raise Conflict("This thread is not waiting on a call to approve.", code="nothing_to_approve")
    if await hitl_facade.is_own_request(rt, row, approver, waiting[0]["payload"]):
        raise Forbidden("You started this, so someone else has to approve it.")
    policy = await policy_of(rt, call["tool"])
    hitl_facade.require_approver_team(policy, approver_teams, call["tool"])
    if policy.approvers > 1:
        require_step_up(rt, approver, step_up_token)
    digest = input_hash(call["input"])
    # Two approvers means two people: approving the same input again does not count as the second. Only approvals
    # of this exact input count: an approval of an earlier draft of the call is not one of these.
    found = await ReviewStore(graph_store(rt).engine).approve(
        thread_id, call["step"], approver, digest, distinct=policy.approvers > 1
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
async def list_reviews(rt: Rt, q: Annotated[ReviewsQuery, Query()]) -> JSONResponse:
    filters = {"risk": q.risk, "workflowId": q.workflowId, "kind": q.kind, "agentSlug": q.agentSlug, "status": q.status}
    rows = await hitl_facade.list_reviews(
        rt, view=q.view, filters=filters, search=q.search, page_no=q.page, size=q.pageSize
    )
    return ok(rows)


@console_router.get("/{thread_id}", response_model=Envelope[Review])
async def get_review(rt: Rt, thread_id: str) -> JSONResponse:
    return ok(await hitl_facade.get_review(rt, thread_id))


@console_router.post("/{thread_id}/decision", response_model=Envelope[Review])
async def decide(rt: Rt, me: Me, thread_id: str, body: ReviewDecisionInput) -> JSONResponse:
    review = await hitl_facade.decide(
        rt,
        me.email,
        thread_id,
        decision=body.decision,
        reason=body.reason or None,
        step_up_token=body.step_up_token,
        approver_teams=teams_of(me),
    )
    return ok(review)


class BulkDecisionInput(WireModel):
    ids: list[str]
    decision: str
    reason: str | None = None
    step_up_token: str | None = None


class AssignInput(WireModel):
    ids: list[str]
    assignee: str | None = None


@console_router.post("/bulk-decision", response_model=Envelope[BulkResult])
async def bulk_decide(rt: Rt, me: Me, body: BulkDecisionInput) -> JSONResponse:
    updated: list[str] = []
    skipped: list[dict[str, str]] = []
    for thread_id in body.ids:
        try:
            await hitl_facade.decide(
                rt,
                me.email,
                thread_id,
                decision=body.decision,
                reason=body.reason,
                step_up_token=body.step_up_token,
                approver_teams=teams_of(me),
            )
            updated.append(thread_id)
        except ApiError as e:
            skipped.append({"id": thread_id, "reason": e.message})
    return ok({"updated": updated, "skipped": skipped})


@console_router.post("/assign", response_model=Envelope[BulkResult])
async def assign(body: AssignInput) -> JSONResponse:
    # Assignment of reviews to people belongs to hitl-service, which does not exist yet; every id is reported skipped.
    reason = "Workflow reviews cannot be assigned yet."
    return ok({"updated": [], "skipped": [{"id": i, "reason": reason} for i in body.ids]})
