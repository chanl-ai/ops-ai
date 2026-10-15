"""GET /v1/tools: the tools an agent can be granted, from tools-service's registry (activities/tool_directory.py), so
the console's agent page grants real, published operations. `known_tools` is the one lookup behind it and behind the
agents routes' grant check."""

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


async def known_tools(rt: Runtime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for op in await rt.directory().operations():
        # A reviewer card template, where the fixture catalogue has one; registry operations get the generic card.
        template = (d := rt.catalog.tool(op.name)) and d.approval
        rows.append(
            {
                "id": op.name,
                "name": op.name,
                "server": op.module_name,
                "moduleId": op.module_id,
                "description": op.description,
                "access": op.access,
                "inputSchema": op.input_schema,
                "requiresApproval": op.requires_approval,
                "approval": template.title if template else None,
            }
        )
    return rows


@router.get("", response_model=Envelope[list[Tool]])
async def list_tools(rt: Rt) -> JSONResponse:
    return ok(await known_tools(rt))
