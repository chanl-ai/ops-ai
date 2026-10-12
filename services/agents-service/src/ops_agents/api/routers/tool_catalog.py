"""GET /v1/tools: the tools an agent can be granted, from the runtime catalogue, so the console's agent page grants
real tool ids. `known_tools` is the one lookup behind it and behind the agents routes' grant check; when the
catalogue moves to tools-service it becomes an HTTP call there, as `tool_access.access_of` is for reviews."""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..auth import principal
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import Envelope, Tool

router = APIRouter(prefix="/v1/tools", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases


def known_tools(rt: Runtime) -> list[dict[str, Any]]:
    return [
        {
            "id": t.name,
            "name": t.name,
            "server": t.server,
            "description": t.description,
            "access": t.access,
            "approval": t.approval.title if t.approval else None,
        }
        for t in rt.catalog.tools
    ]


@router.get("", response_model=Envelope[list[Tool]])
async def list_tools(rt: Rt) -> JSONResponse:
    return ok(known_tools(rt))
