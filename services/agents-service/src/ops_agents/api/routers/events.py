"""Reading the thread event log: re-attach to one run from a cursor, and the team's stream of thread lifecycle events.

Both are SSE. With `follow` (the default) they keep polling the log, the run stream until the run has ended and the
team stream until the client disconnects. `follow=false` returns what is stored and closes, which is what an
in-process test can read (the ASGI test transport buffers a stream until it ends).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends
from sse_starlette import EventSourceResponse

from ops_service_kit.errors import NotFound

from ...store.events import EventLog
from ..auth import Principal, principal
from ..deps import Runtime, runtime
from ..runs import graph_store
from ..schemas import SSE_RESPONSE

router = APIRouter(dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040

POLL_SECONDS = 0.25


async def run_frames(
    rt: Runtime, thread_id: str, run_id: str, after: int, *, follow: bool
) -> AsyncGenerator[dict[str, str]]:
    store = graph_store(rt)
    cursor = after
    while True:
        batch = await EventLog(store.engine).run_events(thread_id, run_id, cursor)
        for e in batch:
            cursor = e["seq"]
            yield {"id": str(e["seq"]), "event": e["type"], "data": json.dumps(e, ensure_ascii=False)}
        if not follow:
            return
        # Ends when the run has, not at the first terminal type: the paused node's own end event follows `waiting`.
        run = await store.run(run_id)
        if not batch and (run is None or run["status"] != "running"):
            return
        await asyncio.sleep(POLL_SECONDS)


async def team_frames(rt: Runtime, team_id: str, after: int, *, follow: bool) -> AsyncGenerator[dict[str, str]]:
    engine = graph_store(rt).engine
    cursor = after
    while True:
        batch = await EventLog(engine).team_events(team_id, cursor)
        for position, e in batch:
            cursor = position
            yield {"id": str(position), "event": f"thread.{e['type']}", "data": json.dumps(e, ensure_ascii=False)}
        if not follow:
            return
        if not batch:
            await asyncio.sleep(POLL_SECONDS)


@router.get("/v1/threads/{thread_id}/runs/{run_id}/events", response_model=None, responses=SSE_RESPONSE)
async def reattach(rt: Rt, thread_id: str, run_id: str, after: int = 0, follow: bool = True) -> EventSourceResponse:
    """The run's events with `seq` above `after`, in the designed shape; the SSE `id` is the seq to resume from."""
    run = await graph_store(rt).run(run_id)
    if run is None or run["thread_id"] != thread_id:
        raise NotFound("Run")
    return EventSourceResponse(run_frames(rt, thread_id, run_id, after, follow=follow), sep="\n", ping=15)


@router.get("/v1/events", response_model=None, responses=SSE_RESPONSE)
async def team_stream(rt: Rt, me: Me, after: int = 0, follow: bool = True) -> EventSourceResponse:
    """Thread lifecycle events for the caller's team: started, waiting, waiting_review, decided, finished, failed.
    The SSE `id` is the stream position to pass back as `after`."""
    return EventSourceResponse(team_frames(rt, me.team_id, after, follow=follow), sep="\n", ping=15)
