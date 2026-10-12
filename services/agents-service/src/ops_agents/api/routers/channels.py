"""Deployments (a graph on a channel, with settings) and a thread's inbox of channel messages (E6)."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_contracts.chat import WireModel
from ops_service_kit.errors import NotFound, ValidationFailed
from ops_service_kit.ids import now_iso

from ...store.channels import ChannelStore, Deployment
from ..auth import principal
from ..channels.inbox import deliver
from ..deps import Runtime, runtime
from ..envelope import ok
from ..runs import resolve
from ..schemas import DeploymentPaused, DeploymentView, Envelope, InboxItem, InboxPosted
from .graphs import BudgetInput

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases

deployments_router = APIRouter(prefix="/v1/deployments", dependencies=[Depends(principal)])
inbox_router = APIRouter(prefix="/v1/threads", dependencies=[Depends(principal)])


class DeploymentInput(WireModel):
    id: str
    graph: str
    channel: Literal["mailbox", "widget", "api", "mcp"]
    paused: bool = False
    multitask: Literal["enqueue", "reject"] = "enqueue"
    # Default caps for each case the deployment opens (E12).
    budget: BudgetInput | None = None


class PauseInput(WireModel):
    paused: bool


class InboxInput(WireModel):
    kind: Literal["customer_reply"]
    message_key: str
    payload: dict[str, Any]


def _channels(rt: Runtime) -> ChannelStore:
    if rt.channels is None:
        raise ValidationFailed("Channels are not available in this process.")
    return rt.channels


@deployments_router.post("", response_model=Envelope[DeploymentView], status_code=201)
async def put_deployment(rt: Rt, body: DeploymentInput) -> JSONResponse:
    if body.graph not in rt.graphs and not await rt.graph_store.versions(body.graph):  # pyright: ignore[reportOptionalMemberAccess]
        raise ValidationFailed(f"Unknown graph {body.graph}.")
    await _channels(rt).put_deployment(
        Deployment(
            body.id,
            body.graph,
            body.channel,
            body.paused,
            body.multitask,
            body.budget.model_dump(mode="json", exclude_none=True) if body.budget else None,
        ),
        now_iso(),
    )
    return ok(body.wire(), status=201)


@deployments_router.patch("/{deployment_id}", response_model=Envelope[DeploymentPaused])
async def pause_deployment(rt: Rt, deployment_id: str, body: PauseInput) -> JSONResponse:
    if not await _channels(rt).set_paused(deployment_id, body.paused):
        raise NotFound(f"Deployment {deployment_id}")
    return ok({"id": deployment_id, "paused": body.paused})


@inbox_router.post("/{thread_id}/inbox", response_model=Envelope[InboxPosted])
async def post_inbox(rt: Rt, thread_id: str, body: InboxInput) -> JSONResponse:
    outcome, seq = await deliver(rt, thread_id, key=body.message_key, kind=body.kind, payload=body.payload)
    return ok({"threadId": thread_id, "status": outcome, "seq": seq})


@inbox_router.get("/{thread_id}/inbox", response_model=Envelope[list[InboxItem]])
async def get_inbox(rt: Rt, thread_id: str) -> JSONResponse:
    await resolve(rt, thread_id)
    rows = await _channels(rt).inbox(thread_id)
    return ok(
        [{"seq": r["seq"], "messageKey": r["message_key"], "kind": r["kind"], "status": r["status"]} for r in rows]
    )
