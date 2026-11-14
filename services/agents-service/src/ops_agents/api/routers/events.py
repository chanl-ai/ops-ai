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
from ..chat_threads import may_read_thread
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


async def team_frames(
    rt: Runtime, me: Principal, team_id: str, after: int, *, follow: bool
) -> AsyncGenerator[dict[str, str]]:
    """The team's lifecycle events of the threads the caller may read (`may_read_thread`): a teammate's chat moving
    through its states is left out, so the stream does not name it."""
    store = graph_store(rt)
    cursor = after
    # Each thread's answer once per stream: who may read a thread does not change while it is followed.
    readable: dict[str, bool] = {}
    while True:
        batch = await EventLog(store.engine).team_events(team_id, cursor)
        for position, e in batch:
            cursor = position
            thread_id = str(e["threadId"])
            if thread_id not in readable:
                row = await store.thread(thread_id)
                readable[thread_id] = row is not None and may_read_thread(row, me)
            if not readable[thread_id]:
                continue
            yield {"id": str(position), "event": f"thread.{e['type']}", "data": json.dumps(e, ensure_ascii=False)}
        if not follow:
            return
        if not batch:
            await asyncio.sleep(POLL_SECONDS)


@router.get("/v1/threads/{thread_id}/runs/{run_id}/events", response_model=None, responses=SSE_RESPONSE)
async def reattach(
    rt: Rt, me: Me, thread_id: str, run_id: str, *, after: int = 0, follow: bool = True
) -> EventSourceResponse:
    """The run's events with `seq` above `after`, in the designed shape; the SSE `id` is the seq to resume from. Not
    found for a run of a thread the caller may not read (`may_read_thread`)."""
    store = graph_store(rt)
    thread = await store.thread(thread_id)
    run = await store.run(run_id)
    if thread is None or not may_read_thread(thread, me) or run is None or run["thread_id"] != thread_id:
        raise NotFound("Run")
    return EventSourceResponse(run_frames(rt, thread_id, run_id, after, follow=follow), sep="\n", ping=15)


@router.get("/v1/events", response_model=None, responses=SSE_RESPONSE)
async def team_stream(rt: Rt, me: Me, after: int = 0, follow: bool = True) -> EventSourceResponse:
    """Thread lifecycle events for the caller's team: started, waiting, waiting_review, decided, finished, failed.
    The SSE `id` is the stream position to pass back as `after`."""
    return EventSourceResponse(team_frames(rt, me, me.team_id, after, follow=follow), sep="\n", ping=15)
