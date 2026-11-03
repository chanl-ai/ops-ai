"""GET /v1/tools: the tools an agent can be granted, from tools-service's registry (activities/tool_directory.py), so
the console's agent page grants real, published operations. `known_tools` is the one lookup behind it and behind the
agents routes' grant check."""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from ops_service_kit.errors import NotFound
from ops_service_kit.http import Envelope, OptionsPage, options_page, options_window, page_window, paged

from ...store.tenancy import current_team
from ..auth import Principal, principal
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
from ..schemas import ToolList, ToolRow

router = APIRouter(prefix="/v1/tools", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases


async def known_tools(rt: Runtime, *, fresh: bool = False) -> list[dict[str, Any]]:
    """Registry operations, then the tenant's published workflows (from this service's own workflow registry) under
    `workflow:<id>`: what an agent may be granted, and what search_tools finds among an agent's grants. `fresh` asks
    tools-service again past the 30 s list, for a grant naming a tool the kept list lacks (c-607)."""
    # Only a directory that keeps a list has one to drop; a fixed catalogue or a test's list has none.
    if fresh and (forget := getattr(rt.directory(), "forget", None)) is not None:
        forget()
    rows: list[dict[str, Any]] = []
    for op in await rt.directory().operations():
        # A reviewer card template, where the fixture catalogue has one; registry operations get the generic card.
        template = (d := rt.catalog.tool(op.name)) and d.approval
        rows.append(
            {
                "id": op.name,
                "name": op.name,
                "title": getattr(op, "title", None),
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
    from ..agent_calls import QUESTION_SCHEMA  # noqa: PLC0415 - keep the catalog import cycle out of the module top

    for a in rt.catalog.agents:
        rows.append(
            {
                "id": f"agent:{a.id}",
                "name": a.name,
                "server": "Agents",
                "moduleId": None,
                "description": f"Ask {a.name}, the {a.role}.",
                "access": "read",
                "inputSchema": QUESTION_SCHEMA,
                "requiresApproval": False,
                "approval": None,
            }
        )
    return rows


# The row fields the page filters and counts by; each filter is repeatable.
FACETS = ("app", "kind", "status")
# An app's state that leaves its tools runnable: connected, or connected with a failed test (a warning).
RUNNABLE = ("connected", "test_failed")


def _kind_of(tool: dict[str, Any], card: dict[str, Any] | None) -> str:
    if tool["access"] == "workflow":
        return "workflow"
    if str(tool["id"]).startswith("agent:"):
        return "agent"
    return "app" if card is not None and card.get("kind") in ("plugin", "builtin") else "custom"


def _status_of(tool: dict[str, Any], card: dict[str, Any] | None) -> str:
    if card is not None and card.get("appState") not in RUNNABLE:
        each_person = card.get("appState") == "needs_sign_in" and card.get("signIn") == "person"
        return "needs_your_sign_in" if each_person else "app_not_connected"
    return "needs_approval" if tool.get("requiresApproval") else "ready"


async def tool_rows(rt: Runtime, person: str | None, team: str | None) -> list[dict[str, Any]]:
    """Every tool the team may grant, one row each, joined in one read of tools-service's apps (for `person`) and one
    of this service's own grants and workflow steps."""
    from .tool_uses import tool_uses  # noqa: PLC0415 - keep the catalog import cycle out of the module top

    tools = await known_tools(rt)
    cards = await rt.app_states.cards(person, team) if rt.app_states is not None else []
    by_module = {str(m): c for c in cards for m in cast(list[str], c.get("moduleIds") or [])}
    uses = await tool_uses(rt, team or current_team(), [str(t["id"]) for t in tools])
    rows: list[dict[str, Any]] = []
    for t in tools:
        module = t.get("moduleId")
        card = by_module.get(str(module)) if module else None
        app = {"id": card["id"], "name": card["name"]} if card else None
        if app is None and module:
            app = {"id": f"module:{module}", "name": t["server"]}
        used = uses.get(str(t["id"])) or []
        by = {k: [{"id": u["id"], "name": u["name"]} for u in used if u["kind"] == k] for k in ("agent", "workflow")}
        rows.append(
            {
                **t,
                "title": t.get("title") or t["name"],
                "app": app,
                "kind": _kind_of(t, card),
                "status": _status_of(t, card),
                "usedBy": {"agents": by["agent"], "workflows": by["workflow"]},
            }
        )
    return rows


def _person(p: Principal) -> str | None:
    """The person a list is read for: their email, as the acting-for token names them; none for a key or service."""
    return p.email if not p.is_key and "@" in p.email else None


def _app(row: dict[str, Any]) -> dict[str, str]:
    return cast(dict[str, str], row.get("app") or {})


def _facet(row: dict[str, Any], column: str) -> str | None:
    """The value a row is counted and filtered by: its app's id, or its kind or status."""
    return _app(row).get("id") if column == "app" else str(row[column])


@router.get("", response_model=Envelope[ToolList])
async def list_tools(
    rt: Rt,
    request: Request,
    p: Annotated[Principal, Depends(principal)],
    *,
    page_no: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
    search: Annotated[str, Query(max_length=200)] = "",
) -> JSONResponse:
    """The Tools page: one row per tool with its app, kind, status and users, searched, filtered (`app`, `kind`,
    `status`, each repeatable) and paged here. Facets count every row the search matches, before the filters."""
    rows = await tool_rows(rt, _person(p), p.team_id)
    q = search.strip().lower()
    if q:
        rows = [
            r for r in rows if q in f"{r['title']} {r['name']} {_app(r).get('name', '')} {r['description']}".lower()
        ]
    facets: dict[str, dict[str, int]] = {c: {} for c in FACETS}
    for r in rows:
        for c in FACETS:
            if (value := _facet(r, c)) is not None:
                facets[c][value] = facets[c].get(value, 0) + 1
    for c in FACETS:
        if wanted := request.query_params.getlist(c):
            rows = [r for r in rows if _facet(r, c) in wanted]
    rows.sort(key=lambda r: (_app(r).get("name") or "~", str(r["title"]).lower()))
    page_no, start = page_window(len(rows), page_no, page_size)
    return ok({**paged(rows[start : start + page_size], len(rows), page_no, page_size), "facets": facets})


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
        hits = [t for t in tools if q in f"{t.get('title') or ''} {t['name']} {t['server']} {t['description']}".lower()]
        offset, _ = options_window(cursor, limit)
    page = hits[offset : offset + limit + 1]
    # A plugin tool reads by its title (c-581); every other tool by its name.
    options = [
        {"id": t["id"], "label": t.get("title") or t["name"], "hint": t["server"], "disabled": None} for t in page
    ]
    return ok(options_page(options, offset, limit))


@router.get("/{tool_id}", response_model=Envelope[ToolRow])
async def get_tool(rt: Rt, tool_id: str, p: Annotated[Principal, Depends(principal)]) -> JSONResponse:
    """One tool as its row on the Tools page reads; declared after /options so that path is not read as a tool."""
    row = next((r for r in await tool_rows(rt, _person(p), p.team_id) if r["id"] == tool_id), None)
    if row is None:
        raise NotFound(f"Tool {tool_id}")
    return ok(row)
