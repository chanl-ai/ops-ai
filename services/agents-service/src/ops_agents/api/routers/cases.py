"""Cases: workflow runs across every thread, on the console's `/runs` routes (see hitl_facade).

Neither route takes the request transaction (`Tx`): each row names the team that decides its step through
platform-service (`deciding_team`) and a held tool call's write policy through tools-service, and no connection is held
while they answer. The list pages rows computed from several stores in memory rather than in SQL."""

from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ops_service_kit.http import Envelope
from ops_store import isolation

from .. import hitl_facade
from ..auth import reader_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import CaseRun, CaseRunList

# The cases list and one case name customers and their steps, so both need cases.view where the request acts.
router = APIRouter(prefix="/runs", dependencies=[Depends(reader_of("cases"))])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases


class RunsQuery(BaseModel):
    view: str = "open"
    page: int = 1
    pageSize: int = 25  # noqa: N815 - the console's query parameter
    search: str | None = None
    workflowId: list[str] = Field(default_factory=list[str])  # noqa: N815
    state: list[str] = Field(default_factory=list[str])
    queue: list[str] = Field(default_factory=list[str])
    # The child cases of one thread (a levy notice's cases), by its id.
    parent: list[str] = Field(default_factory=list[str])


@router.get("", response_model=Envelope[CaseRunList])
async def list_runs(rt: Rt, q: Annotated[RunsQuery, Query()]) -> JSONResponse:
    filters = {"workflowId": q.workflowId, "state": q.state, "queue": q.queue, "parentThreadId": q.parent}
    # Local reads only (no other service is asked), so one transaction holds them all.
    async with isolation.request_transaction():
        rows = await hitl_facade.list_runs(
            rt, view=q.view, filters=filters, search=q.search, page_no=q.page, size=q.pageSize
        )
    return ok(rows)


@router.get("/{thread_id}", response_model=Envelope[CaseRun])
async def get_run(rt: Rt, thread_id: str) -> JSONResponse:
    async with isolation.request_transaction():
        return ok(await hitl_facade.get_run(rt, thread_id))
