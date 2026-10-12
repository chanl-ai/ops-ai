"""/v1/publish-requests: reading and deciding agent and workflow publish requests outside dev's auto-approve.

The decision body is the reviews decide shape (`ReviewDecisionInput`: decision, reason). The rule is the reviews
rule: the person who asked cannot decide, and for an agent neither can the person who saved the version
(maker-checker). Rejecting or returning needs a reason. Approving publishes what the request recorded: the agent
version, or the workflow definition as compiled when it was requested, with the agent pins the reviewer saw.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_contracts.chat import WireModel

from .. import publish_reviews
from ..auth import Principal, principal
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import Envelope, PublishReview

router = APIRouter(prefix="/v1/publish-requests", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040


class DecisionInput(WireModel):
    decision: Literal["approved", "rejected", "returned"]
    reason: str | None = None


@router.get("/{request_id}", response_model=Envelope[PublishReview])
async def get_publish_request(rt: Rt, request_id: str) -> JSONResponse:
    return ok(await publish_reviews.get(rt, request_id))


@router.post("/{request_id}/decision", response_model=Envelope[PublishReview])
async def decide_publish_request(rt: Rt, me: Me, request_id: str, body: DecisionInput) -> JSONResponse:
    return ok(await publish_reviews.decide(rt, me.email, request_id, decision=body.decision, reason=body.reason))
