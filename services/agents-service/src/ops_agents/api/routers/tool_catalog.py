"""GET /v1/tools: the tools an agent can be granted, from tools-service's registry (activities/tool_directory.py), so
the console's agent page grants real, published operations. `known_tools` is the one lookup behind it and behind the
agents routes' grant check.

No route here takes the request transaction (`Tx`): each reads tools-service's operations or app cards between its
reads of this service's rows, so each store call takes and returns its own connection and none is held while
tools-service answers."""

from __future__ import annotations

from typing import Annotated, NotRequired, TypeAlias, TypedDict, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from ops_service_kit.errors import NotFound
from ops_service_kit.http import Envelope, Json, options_page, options_window, page_window, pagination
from ops_store import isolation

from ...activities.tool_directory import ToolsUnavailable
from ...store.tenancy import current_team
from ..agent_registry import registry
from ..auth import Principal, principal, reader_of
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
from ..schemas import ToolList, ToolOptionsPage, ToolRow

router = APIRouter(prefix="/v1/tools", dependencies=[Depends(principal)])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases


class ToolEntry(TypedDict):
    """A tool as the catalogue lists it; `title` only on a registry operation."""

    id: str
    name: str
    title: NotRequired[str | None]
    server: str
    moduleId: str | None
    description: str
    access: str
    inputSchema: Json
    requiresApproval: bool
    approval: str | None


ToolRows = list[ToolEntry]


class AppRef(TypedDict):
    id: str
    name: str


class UserRef(TypedDict):
    id: str
    name: str


class UsedBy(TypedDict):
    agents: list[UserRef]
    workflows: list[UserRef]


class CatalogRow(TypedDict):
    """One row of the Tools page: the catalogue's tool, then its app, kind, status and users."""

    id: str
    name: str
    title: str
    server: str
    moduleId: str | None
    description: str
    access: str
    inputSchema: Json
    requiresApproval: bool
    approval: str | None
    app: AppRef | None
    kind: str
    status: str
    usedBy: UsedBy


class NotAdded(TypedDict):
    appId: str
    name: str
    count: int


async def directory_tools(rt: Runtime, *, fresh: bool = False) -> ToolRows:
    """The registry's operations as tool rows: the one call to tools-service, made with nothing open. `fresh` asks
    tools-service again past the 30 s list, for a grant naming a tool the kept list lacks."""
    # Only a directory that keeps a list has one to drop; a fixed catalogue or a test's list has none.
    if fresh and (forget := getattr(rt.directory(), "forget", None)) is not None:
        forget()
    rows: ToolRows = []
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
    return rows


async def known_tools(rt: Runtime, *, fresh: bool = False, listed: ToolRows | None = None) -> ToolRows:
    """Registry operations, then the tenant's published workflows (from this service's own workflow registry) under
    `workflow:<id>`: what an agent may be granted, and what search_tools finds among an agent's grants. `listed` is
    the operations a caller already fetched with `directory_tools`, so its local reads can share one transaction."""
    rows = list(listed) if listed is not None else await directory_tools(rt, fresh=fresh)
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

    # The catalogue holds every tenant's agents; only the caller's tenant's are its tools.
    ours = await registry(rt).tenant_owners({a.id for a in rt.catalog.agents})
    for a in (a for a in rt.catalog.agents if a.id in ours):
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


def _kind_of(tool: ToolEntry, card: Json | None) -> str:
    if tool["access"] == "workflow":
        return "workflow"
    if str(tool["id"]).startswith("agent:"):
        return "agent"
    return "app" if card is not None and card.get("kind") in ("plugin", "builtin") else "custom"


def _status_of(tool: ToolEntry, card: Json | None) -> str:
    if card is not None and card.get("appGroup") != "on":
        # tools-service says who acts next: the person's own sign-in, or the team's (an admin).
        return "needs_your_sign_in" if card.get("appGroup") == "needs_you" else "app_not_connected"
    return "needs_approval" if tool.get("requiresApproval") else "ready"


def app_of(tool: ToolEntry, card: Json | None) -> AppRef | None:
    """The app a tool belongs to: its module's app card, else its module under the server's name; None for a
    workflow or an agent, which have no module."""
    if card is not None:
        # The card's id and name pass through as tools-service sends them (its schema says strings).
        return {"id": cast(str, card["id"]), "name": cast(str, card["name"])}
    module = tool.get("moduleId")
    return {"id": f"module:{module}", "name": tool["server"]} if module else None


async def tool_rows(rt: Runtime, person: str | None, team: str | None) -> list[CatalogRow]:
    """Every tool the team may grant, one row each, joined in one read of tools-service's apps (for `person`) and one
    of this service's own grants and workflow steps. tools-service is asked for the apps and the operations before
    any statement, so the local reads that follow share one transaction with nothing called while it is open."""
    from .tool_uses import tool_uses  # noqa: PLC0415 - keep the catalog import cycle out of the module top

    cards = await rt.app_states.cards(person, team) if rt.app_states is not None else []
    by_module = {str(m): c for c in cards for m in cast(list[str], c.get("moduleIds") or [])}
    async with isolation.request_transaction():
        # A person's page reads the list fresh: a tool added to the team a moment ago shows at once.
        tools = await known_tools(rt, fresh=True)
        uses = await tool_uses(rt, team or current_team(), [str(t["id"]) for t in tools])
    rows: list[CatalogRow] = []
    for t in tools:
        module = t.get("moduleId")
        card = by_module.get(str(module)) if module else None
        app = app_of(t, card)
        used = uses.get(str(t["id"])) or []
        by: dict[str, list[UserRef]] = {
            k: [{"id": u["id"], "name": u["name"]} for u in used if u["kind"] == k] for k in ("agent", "workflow")
        }
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


def person_of(p: Principal) -> str | None:
    """The person a list is read for: their email, as the acting-for token names them; none for a key or service."""
    return p.email if not p.is_key and "@" in p.email else None


def _app_name(row: CatalogRow) -> str | None:
    return app["name"] if (app := row["app"]) else None


def _facet(row: CatalogRow, column: str) -> str | None:
    """The value a row is counted and filtered by: its app's id, or its kind or status."""
    if column == "app":
        return app["id"] if (app := row["app"]) else None
    return str(row["kind"] if column == "kind" else row["status"])


@router.get("", response_model=Envelope[ToolList])
async def list_tools(
    rt: Rt,
    request: Request,
    p: Annotated[Principal, Depends(reader_of("tools"))],
    *,
    page_no: Annotated[int, Query(alias="page", ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
    search: Annotated[str, Query(max_length=200)] = "",
) -> JSONResponse:
    """The Tools page: one row per tool with its app, kind, status and users, searched, filtered (`app`, `kind`,
    `status`, each repeatable) and paged here. Facets count every row the search matches, before the filters, and
    `appNames` names each app the app facet counts."""
    rows = await tool_rows(rt, person_of(p), p.team_id)
    q = search.strip().lower()
    if q:
        rows = [r for r in rows if q in f"{r['title']} {r['name']} {_app_name(r) or ''} {r['description']}".lower()]
    facets: dict[str, dict[str, int]] = {c: {} for c in FACETS}
    names: dict[str, str] = {}
    for r in rows:
        for c in FACETS:
            if (value := _facet(r, c)) is not None:
                facets[c][value] = facets[c].get(value, 0) + 1
        if app := r["app"]:
            names[app["id"]] = app["name"]
    for c in FACETS:
        if wanted := request.query_params.getlist(c):
            rows = [r for r in rows if _facet(r, c) in wanted]
    # The id last, so two tools of one app with one title keep their order from page to page.
    rows.sort(key=lambda r: (_app_name(r) or "~", str(r["title"]).lower(), str(r["id"])))
    page_no, start = page_window(len(rows), page_no, page_size)
    # By name, the order the App filter lists them in.
    names = dict(sorted(names.items(), key=lambda kv: kv[1].lower()))
    # `paged` takes loose rows; the same four keys, in its order.
    return ok(
        {
            "data": rows[start : start + page_size],
            "pagination": pagination(len(rows), page_no, page_size),
            "facets": facets,
            "appNames": names,
        }
    )


async def not_added(rt: Runtime, team: str | None, search: str) -> list[NotAdded]:
    """The team's apps whose name matches `search` and whose catalog holds tools the team has not added, with how many.
    Read from tools-service's app cards; when it cannot be reached the picker still answers, without this line."""
    if rt.app_states is None:
        return []
    try:
        cards = await rt.app_states.cards(None, team)
    except ToolsUnavailable:
        return []
    q = search.strip().lower()
    return [
        {
            "appId": str(c["id"]),
            "name": str(c["name"]),
            "count": int(cast(float | str, c["toolsCount"])) - int(cast(float | str, c["toolsAdded"])),
        }
        for c in cards
        if c.get("toolsAdded") is not None
        and int(cast(float | str, c["toolsCount"])) > int(cast(float | str, c["toolsAdded"]))
        and (not q or q in str(c["name"]).lower())
    ]


# The admin's one choice per app, as the console's app page words it (apps/console/src/lib/login-words.ts).
SIGN_IN_WORDS = {
    "team": "Everyone uses the team's login",
    "person": "Each person signs in",
    "person_or_team": "Each person signs in",
}


async def sign_in_by_module(rt: Runtime, team: str | None) -> dict[str, str]:
    """Each module's app sign-in in words, from tools-service's app cards; empty when it cannot be reached."""
    if rt.app_states is None:
        return {}
    try:
        cards = await rt.app_states.cards(None, team)
    except ToolsUnavailable:
        return {}
    out: dict[str, str] = {}
    for c in cards:
        words = SIGN_IN_WORDS.get(str(c.get("signIn") or ""))
        for m in cast(list[str], c.get("moduleIds") or []):
            if words:
                out[str(m)] = words
    return out


async def team_tools(rt: Runtime, team: str | None, *, fresh: bool = False, listed: ToolRows | None = None) -> ToolRows:
    """`known_tools` less another team's v1 workflows and agents: what an agent of `team` may be granted. v2
    workflows come scoped to the selected team already; v1 registry workflows and agents carry a team. Operations are
    tenant-wide, as the grant check offers them."""
    known = await (known_tools(rt, fresh=fresh) if listed is None else known_tools(rt, listed=listed))
    if not team:
        return known
    others = {f"workflow:{w['id']}" for w in await published_workflows(rt) if w.get("team_id") not in (None, "", team)}
    agents = {str(t["id"]).removeprefix("agent:") for t in known if str(t["id"]).startswith("agent:")}
    owners = await registry(rt).tenant_owners(agents)
    others |= {f"agent:{a}" for a, owner in owners.items() if owner not in ("", team)}
    return [t for t in known if t["id"] not in others]


def options_cut[T](rows: list[T], offset: int, limit: int) -> list[T]:
    """The rows an `/options` page answers from, read as `options_window` says (one past `limit`): the lists here are
    the directory tools-service sends, with no rows to query, so they are cut in Python."""
    return rows[offset : offset + limit + 1]


@router.get("/options", response_model=Envelope[ToolOptionsPage], dependencies=[Depends(reader_of("tools"))])
async def tool_options(
    rt: Rt,
    *,
    search: str = "",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    ids: Annotated[list[str] | None, Query()] = None,
    # `agents=false` leaves agents out: an MCP link's picker, whose door runs tools and workflows only.
    agents: bool = True,
) -> JSONResponse:
    """The agent page's tools picker: grantable operations, then the team's workflows, searched by name, module and
    description and paged here, so the browser receives one page. Operations live inside each module's document in
    tools-service and have no rows to query, so the search runs over the directory this service already caches (30 s)
    rather than in a store query. `ids` labels stored grants instead of searching; a name no longer offered is left
    out."""
    team = current_team()
    # One transaction for the local reads: `known_tools` asks tools-service before its first statement, so nothing
    # is called while it is open; the not-added line after it asks tools-service with it closed.
    async with isolation.request_transaction():
        # The agent and workflow pickers read it fresh, so a tool just added to the team is offered at once.
        known = await team_tools(rt, team, fresh=True)
    tools = [t for t in known if agents or not str(t["id"]).startswith("agent:")]
    if ids is not None:
        wanted = set(ids)
        hits = [t for t in tools if t["id"] in wanted]
        offset = 0
    else:
        q = search.strip().lower()
        hits = [t for t in tools if q in f"{t.get('title') or ''} {t['name']} {t['server']} {t['description']}".lower()]
        offset, _ = options_window(cursor, limit)
    page = options_cut(hits, offset, limit)
    # The agent's tools rows (stored grants) say who signs in to each tool's app, in the app page's words.
    signs = await sign_in_by_module(rt, team) if ids is not None else {}
    # A plugin tool reads by its title; every other tool by its name.
    options = [
        {
            "id": t["id"],
            "label": t.get("title") or t["name"],
            "hint": " · ".join(x for x in (str(t["server"]), signs.get(str(t.get("moduleId") or ""))) if x),
            "disabled": None,
        }
        | ({} if agents else {"inputSchema": t.get("inputSchema"), "description": t.get("description")})
        for t in page
    ]
    # Said once, above the first page of a search; labelling stored grants says nothing about the catalog.
    waiting = await not_added(rt, team, search) if ids is None and offset == 0 else []
    return ok({**options_page(options, offset, limit), "notAdded": waiting})


@router.get("/{tool_id}", response_model=Envelope[ToolRow])
async def get_tool(rt: Rt, tool_id: str, p: Annotated[Principal, Depends(reader_of("tools"))]) -> JSONResponse:
    """One tool as its row on the Tools page reads; declared after /options so that path is not read as a tool."""
    row = next((r for r in await tool_rows(rt, person_of(p), p.team_id) if r["id"] == tool_id), None)
    if row is None:
        raise NotFound(f"Tool {tool_id}")
    return ok(row)
