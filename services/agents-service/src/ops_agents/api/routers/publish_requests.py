"""/v1/publish-requests: reading and deciding agent and workflow publish requests outside dev's auto-approve.

The decision body is the reviews decide shape (`ReviewDecisionInput`: decision, reason). The rule is the reviews
rule: the person who asked cannot decide, and for an agent neither can the person who saved the version
(maker-checker). Rejecting or returning needs a reason. Approving publishes what the request recorded: the agent
version, or the workflow definition as compiled when it was requested, with the agent pins the reviewer saw.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_contracts.chat import WireModel
from ops_service_kit.errors import ValidationFailed
from ops_service_kit.http import Envelope

from .. import publish_reviews, tool_module_reviews
from ..auth import Principal, caller, principal
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import PublishReview

router = APIRouter(prefix="/v1/publish-requests", dependencies=[Depends(principal)])
# Opening a tool module review also takes tools-service's own token (c-222), so it sits apart from the routes only
# people call; the route itself decides who may open one.
open_router = APIRouter(prefix="/v1/publish-requests")
# Copies of older tool module reviews come from tools-service alone, with no person behind them (c-163).
# service_principal sets the token's tenant: requests are per tenant (c-333).
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040
Caller: TypeAlias = Annotated[Principal, Depends(caller)]  # noqa: UP040


class DecisionInput(WireModel):
    decision: Literal["approved", "rejected", "returned"]
    reason: str | None = None


class _Op(WireModel):
    name: str
    method: str | None = None
    path: str | None = None
    access: str


class _Changed(_Op):
    fields: list[str]


class ToolModuleDiffInput(WireModel):
    """What tools-service computed the version changes since the published one (c-204)."""

    added: list[_Op] = Field(default_factory=list[_Op])
    removed: list[_Op] = Field(default_factory=list[_Op])
    changed: list[_Changed] = Field(default_factory=list[_Changed])
    hosts_added: list[str] = Field(default_factory=list[str])
    secrets: list[str] = Field(default_factory=list[str])


class ToolModuleReviewInput(WireModel):
    kind: Literal["tool_module"]
    subject_id: str
    module_name: str
    module_version: str
    changes: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    diff: ToolModuleDiffInput | None = None
    security: bool = True
    note: str | None = None
    # Refused unless it is the team the caller acts in; the team always comes from their credentials or token.
    team_id: str | None = None
    # Who asked, when tools-service opens the review with its own token for a person not on the call (its seed's
    # versions waiting for review, c-222); refused on any other call, where the person's credentials say who asked.
    requested_by: str | None = Field(default=None, min_length=3, max_length=320)


@open_router.post("", response_model=Envelope[PublishReview], status_code=201)
async def open_publish_request(
    rt: Rt,
    me: Caller,
    request: Request,
    body: ToolModuleReviewInput,
    x_service_authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """A tool module review (c-163). Opened by tools-service for the person publishing: their credentials name who
    asked and the team, and tools-service's token in `X-Service-Authorization` vouches for the version and changes. Or
    opened by tools-service alone with its token scoped to the module's team, naming in `requestedBy` the person who
    asked (its seed, c-222); the review then says tools-service opened it on their behalf."""
    if me.identity is not None and me.identity.kind == "service":
        req = await tool_module_reviews.open_for(rt, me.identity, body.model_dump(by_alias=True))
    else:
        if body.requested_by is not None:
            # The person's credentials say who asked; a body naming someone else is refused, not obeyed.
            raise ValidationFailed(
                "requestedBy is set only on a service's own call; your credentials say who asked.",
                code="requested_by_forbidden",
            )
        await tool_module_reviews.tools_service(request, x_service_authorization, me.tenant_id)
        req = await tool_module_reviews.open_review(rt, me, body.model_dump(by_alias=True))
    return ok(await publish_reviews.view(rt, req), status=201)


@router.get("/{request_id}", response_model=Envelope[PublishReview])
async def get_publish_request(rt: Rt, request_id: str) -> JSONResponse:
    return ok(await publish_reviews.get(rt, request_id))


@router.post("/{request_id}/decision", response_model=Envelope[PublishReview])
async def decide_publish_request(rt: Rt, me: Me, request_id: str, body: DecisionInput) -> JSONResponse:
    return ok(await publish_reviews.decide(rt, me, request_id, decision=body.decision, reason=body.reason))
