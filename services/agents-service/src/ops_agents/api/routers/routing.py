"""Route a thread, or every open thread of one workflow version, to people: a reviewer or admin of the team decides,
and the requester is recorded on the thread.

No route here takes the request transaction (`Tx`): routing takes the thread's lease and runs the workflow to its next
step, which may call a model or a tool, so each store call takes and returns its own connection and none is held while
the run goes on.
"""

from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_service_kit.errors import ApiError
from ops_service_kit.http import Envelope, In
from ops_service_kit.narrow import json_object

from .. import hitl_facade
from ..auth import Principal, principal, require_reviews_decide, review_teams
from ..deps import Runtime, runtime
from ..envelope import ok
from ..routing import open_threads, route_thread
from ..runs import config, graph_store, pending, resolve
from ..schemas import Routed, RoutedVersion

router = APIRouter(dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040


class RouteThread(In):
    reason: str = Field(min_length=1)


class RouteWorkflow(In):
    workflow_id: str
    version_number: int
    reason: str = Field(min_length=1)


async def _may_route(rt: Runtime, me: Principal, thread_id: str) -> None:
    """Routing a case that waits on a step answers that step, so it is checked as a decision on it is
    (`hitl_facade.check_thread_decider`); a case waiting on nothing needs only the team rule."""
    row, graph = await resolve(rt, thread_id)
    waiting = pending(await graph.aget_state(config(thread_id)))
    if waiting:
        await hitl_facade.check_thread_decider(rt, me, row, json_object(waiting[0]["payload"]), [])


@router.post("/v1/threads/{thread_id}/route-to-people", response_model=Envelope[Routed], status_code=202)
async def route_one(rt: Rt, me: Me, thread_id: str, body: RouteThread) -> JSONResponse:
    """Taking a case from the workflow to people is a decision on it: a reviewer or admin of its team, and for a case
    waiting on a step, whoever may decide that step (`_may_route`)."""
    row = await graph_store(rt).thread_row(thread_id)
    require_reviews_decide(
        review_teams(me), (row.team_id if row is not None else "") or me.team_id, f"routing thread {thread_id}"
    )
    await _may_route(rt, me, thread_id)
    status = await route_thread(rt, thread_id, body.reason, me.email)
    return ok({"threadId": thread_id, "status": status}, status=202)


@router.post("/v1/threads:route-to-people", response_model=Envelope[RoutedVersion], status_code=202)
async def route_version(rt: Rt, me: Me, body: RouteWorkflow) -> JSONResponse:
    """Every open case of a version, in the acting team: a reviewer or admin of that team."""
    require_reviews_decide(review_teams(me), me.team_id, f"routing {body.workflow_id} v{body.version_number}")
    results: list[dict[str, str]] = []
    for tid in await open_threads(rt, body.workflow_id, body.version_number):
        try:
            await _may_route(rt, me, tid)
        except ApiError:
            # A case whose waiting step this person may not decide (their own request) stays where it is.
            results.append({"threadId": tid, "status": "refused"})
            continue
        results.append({"threadId": tid, "status": await route_thread(rt, tid, body.reason, me.email)})
    return ok({"workflowId": body.workflow_id, "versionNumber": body.version_number, "threads": results}, status=202)
