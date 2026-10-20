"""GET /v1/tools: the tools an agent can be granted, from tools-service's registry (activities/tool_directory.py), so
the console's agent page grants real, published operations. `known_tools` is the one lookup behind it and behind the
agents routes' grant check."""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ops_service_kit.http import Envelope, OptionsPage, options_page, options_window

from ...store.tenancy import current_team
from ..auth import principal
from ..child_runs import (
    EMAIL_SCHEMA,
    engine_input_schema,
    engine_tool_description,
    engine_workflows,
    published_workflows,
    workflow_tool_description,
)
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import Tool

router = APIRouter(prefix="/v1/tools", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases


async def known_tools(rt: Runtime) -> list[dict[str, Any]]:
    """Registry operations, then the tenant's published workflows (from this service's own workflow registry) under
    `workflow:<id>`: what an agent may be granted, and what search_tools finds among an agent's grants."""
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
    v1 = {w["id"] for w in await published_workflows(rt)}
    for d in await engine_workflows(rt):
        if d["workflow_id"] in v1:
            continue  # a v1 registry workflow of the same id is the one a grant names
        rows.append(
            {
                "id": f"workflow:{d['workflow_id']}",
                "name": d["name"],
                "server": "Workflows",
                "moduleId": None,
                "description": engine_tool_description(d),
                "access": "workflow",
                "inputSchema": engine_input_schema(dict(d["definition"] or {})),
                "requiresApproval": False,
                "approval": None,
            }
        )
    for w in await published_workflows(rt):
        rows.append(
            {
                "id": f"workflow:{w['id']}",
                "name": w["name"],
                "server": "Workflows",
                "moduleId": None,
                "description": workflow_tool_description(w),
                "access": "workflow",
                "inputSchema": EMAIL_SCHEMA,
                # The workflow's own review steps are its gate, not an approval of the call.
                "requiresApproval": False,
                "approval": None,
            }
        )
    return rows


@router.get("", response_model=Envelope[list[Tool]])
async def list_tools(rt: Rt, access: Annotated[list[str] | None, Query()] = None) -> JSONResponse:
    """`access` (repeatable: read, write, workflow) keeps those kinds only, so a page asking for workflow tools does not
    filter the whole directory itself."""
    tools = await known_tools(rt)
    return ok([t for t in tools if t["access"] in access] if access else tools)


@router.get("/options", response_model=Envelope[OptionsPage])
async def tool_options(
    rt: Rt,
    search: str = "",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ids: Annotated[list[str] | None, Query()] = None,
) -> JSONResponse:
    """The agent page's tools picker: grantable operations, then the team's workflows, searched by name, module and
    description and paged here, so the browser receives one page. Operations live inside each module's document in
    tools-service and have no rows to query, so the search runs over the directory this service already caches (30 s)
    rather than in a store query. `ids` labels stored grants instead of searching; a name no longer offered is left
    out."""
    # v2 workflows come scoped to the selected team already; v1 registry workflows carry a team, so another team's
    # are left out here. Operations are tenant-wide, as the grant check offers them.
    team = current_team()
    others = {
        f"workflow:{w['id']}"
        for w in await published_workflows(rt)
        if team and w.get("team_id") not in (None, "", team)
    }
    tools = [t for t in await known_tools(rt) if t["id"] not in others]
    if ids is not None:
        wanted = set(ids)
        hits = [t for t in tools if t["id"] in wanted]
        offset = 0
    else:
        q = search.strip().lower()
        hits = [t for t in tools if q in f"{t['name']} {t['server']} {t['description']}".lower()]
        offset, _ = options_window(cursor, limit)
    page = hits[offset : offset + limit + 1]
    options = [{"id": t["id"], "label": t["name"], "hint": t["server"], "disabled": None} for t in page]
    return ok(options_page(options, offset, limit))
