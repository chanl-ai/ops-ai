"""R9 routes: route a thread, or every open thread of one workflow version, to people.

Spec runtime-service names the publisher as the caller. Dev auth has no roles, so any signed-in user may call
these routes and the requester is recorded on the thread; the publisher-role check comes with real roles.
"""

from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_contracts.chat import WireModel

from ..auth import Principal, principal
from ..deps import Runtime, runtime
from ..envelope import ok
from ..routing import open_threads, route_thread
from ..schemas import Envelope, Routed, RoutedVersion

router = APIRouter(dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040


class RouteThread(WireModel):
    reason: str = Field(min_length=1)


class RouteWorkflow(WireModel):
    workflow_id: str
    version_number: int
    reason: str = Field(min_length=1)


@router.post("/v1/threads/{thread_id}/route-to-people", response_model=Envelope[Routed], status_code=202)
async def route_one(rt: Rt, me: Me, thread_id: str, body: RouteThread) -> JSONResponse:
    status = await route_thread(rt, thread_id, body.reason, me.email)
    return ok({"threadId": thread_id, "status": status}, status=202)


@router.post("/v1/threads:route-to-people", response_model=Envelope[RoutedVersion], status_code=202)
async def route_version(rt: Rt, me: Me, body: RouteWorkflow) -> JSONResponse:
    threads = await open_threads(rt, body.workflow_id, body.version_number)
    results = [{"threadId": tid, "status": await route_thread(rt, tid, body.reason, me.email)} for tid in threads]
    return ok({"workflowId": body.workflow_id, "versionNumber": body.version_number, "threads": results}, status=202)
