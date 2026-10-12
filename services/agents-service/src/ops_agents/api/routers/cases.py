"""Cases: workflow runs across every thread, on the console's `/runs` routes (see hitl_facade)."""

from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import hitl_facade
from ..auth import principal
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import CaseRun, CaseRunList, Envelope

router = APIRouter(prefix="/runs", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases


class RunsQuery(BaseModel):
    view: str = "open"
    page: int = 1
    pageSize: int = 25  # noqa: N815 - the console's query parameter
    search: str | None = None
    workflowId: list[str] = Field(default_factory=list[str])  # noqa: N815
    state: list[str] = Field(default_factory=list[str])
    queue: list[str] = Field(default_factory=list[str])


@router.get("", response_model=Envelope[CaseRunList])
async def list_runs(rt: Rt, q: Annotated[RunsQuery, Query()]) -> JSONResponse:
    filters = {"workflowId": q.workflowId, "state": q.state, "queue": q.queue}
    rows = await hitl_facade.list_runs(
        rt, view=q.view, filters=filters, search=q.search, page_no=q.page, size=q.pageSize
    )
    return ok(rows)


@router.get("/{thread_id}", response_model=Envelope[CaseRun])
async def get_run(rt: Rt, thread_id: str) -> JSONResponse:
    return ok(await hitl_facade.get_run(rt, thread_id))
