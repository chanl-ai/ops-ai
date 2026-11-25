"""GET /v1/agents/{agent_id}/tool-apps: the tools an agent may be granted, grouped by app, for the agent page's picker.

Each app comes from tools-service's app cards (`connected`, `signIn`, how many tools it has); its tools are the team's
grantable ones (`team_tools`), marked with the agent's own grants. A tool with no card groups under its module, and
workflows and agents under one group each. Search, filter and paging run here over the directory this service keeps,
as `/v1/tools/options` does, since operations have no rows to query.

tools-service is asked first, with nothing open; the agent is then read for the caller's team before any reply is
built, so another team's agent answers 404 and says nothing of the team's tools. When the cards cannot be read the
apps fall back to module names, and when the operations cannot be read only this service's workflows and agents are
listed."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, TypeAlias, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ops_service_kit.errors import NotFound
from ops_service_kit.http import Envelope, Json, options_page, options_window
from ops_store import isolation

from ...activities.tool_directory import ToolsUnavailable
from ...store.tenancy import current_team
from ..agent_registry import registry
from ..auth import Principal, reader_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import AgentToolAppsPage, AppToolsPage
from .tool_catalog import (
    SIGN_IN_WORDS,
    ToolEntry,
    ToolRows,
    app_of,
    directory_tools,
    options_cut,
    person_of,
    team_tools,
)

router = APIRouter(prefix="/v1/agents", dependencies=[Depends(reader_of("tools"))])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Reader: TypeAlias = Annotated[Principal, Depends(reader_of("agents"))]  # noqa: UP040

# The groups of tools that belong to no app: this service's own workflows and agents.
OWN_GROUPS = {"Workflows": ("workflows", "workflows"), "Agents": ("agents", "agents")}
# How many of an app's matching tools a search lists under it.
MATCHES = 5


@dataclass
class Group:
    """One app's card (none for a module with no card, or this service's own groups) and the team's tools in it."""

    id: str
    name: str
    kind: str
    card: Json | None
    tools: list[ToolEntry] = field(default_factory=list[ToolEntry])


def _int(value: object) -> int:
    return int(cast(float | str, value))


def _text(t: ToolEntry) -> str:
    return f"{t.get('title') or ''} {t['name']} {t['description']}".lower()


def _label(t: ToolEntry) -> str:
    # A plugin tool reads by its title; every other tool by its name, as the flat picker labels them.
    return t.get("title") or t["name"]


async def _read(rt: Runtime, p: Principal, agent_id: str) -> tuple[dict[str, Group], set[str]]:
    """Every group with the team's tools, and the tools the agent holds. tools-service is asked first, with nothing
    open; the agent and this service's workflows are read in one transaction after it."""
    team = current_team()
    cards: list[Json] = []
    if rt.app_states is not None:
        try:
            cards = await rt.app_states.cards(person_of(p), team)
        except ToolsUnavailable:
            cards = []
    listed: ToolRows
    try:
        listed = await directory_tools(rt, fresh=True)
    except ToolsUnavailable:
        listed = []
    async with isolation.request_transaction():
        reg = registry(rt)
        row = await reg.row(agent_id)
        spec = (await reg.version(agent_id, row.version)).spec
        tools = await team_tools(rt, team, listed=listed)
    held = {str(t) for t in cast(list[object], spec.get("toolIds") or [])}

    groups: dict[str, Group] = {}
    by_module: dict[str, Json] = {}
    for c in cards:
        groups[str(c["id"])] = Group(str(c["id"]), str(c["name"]), str(c.get("kind") or "plugin"), c)
        for m in cast(list[str], c.get("moduleIds") or []):
            by_module[str(m)] = c
    for t in tools:
        module = t.get("moduleId")
        app = app_of(t, by_module.get(str(module)) if module else None)
        if app is not None:
            key, name, kind = app["id"], app["name"], "custom"
        else:
            key, kind = OWN_GROUPS.get(t["server"], (f"server:{t['server']}", "custom"))
            name = t["server"]
        groups.setdefault(key, Group(key, name, kind, None)).tools.append(t)
    return groups, held


def _connected(g: Group) -> bool:
    # A group with no app card has nothing to connect: its tools run as they are.
    return g.card is None or g.card.get("appGroup") == "on"


def _app(g: Group, held: set[str], q: str) -> Json:
    granted = sum(1 for t in g.tools if t["id"] in held)
    matches = [t for t in g.tools if q in _text(t)][:MATCHES] if q else []
    card = g.card or {}
    return {
        "id": g.id,
        "name": g.name,
        "kind": g.kind if g.kind in ("plugin", "builtin", "custom", "workflows", "agents") else "custom",
        "connected": _connected(g),
        "appGroup": card.get("appGroup"),
        "signIn": SIGN_IN_WORDS.get(str(card.get("signIn") or "")),
        # Every tool the app has, by its card; with no card the team's tools are all that is known of it.
        "toolsTotal": _int(card["toolsCount"]) if card.get("toolsCount") is not None else len(g.tools),
        "toolsOffered": len(g.tools),
        "toolsGranted": granted,
        "matches": [
            {"id": t["id"], "label": _label(t), "access": t["access"], "granted": t["id"] in held} for t in matches
        ],
    }


@router.get("/{agent_id}/tool-apps", response_model=Envelope[AgentToolAppsPage])
async def tool_apps(
    rt: Rt,
    p: Reader,
    agent_id: str,
    *,
    search: Annotated[str, Query(max_length=200)] = "",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    granted: bool | None = None,
) -> JSONResponse:
    """The apps whose tools the agent may be granted, connected first, then by name. `search` matches an app's name or
    the title, name and description of one of its tools, which are listed under it (`matches`). `granted=true` keeps
    the apps the agent holds a tool of; `granted=false` the apps with a tool it does not hold yet."""
    groups, held = await _read(rt, p, agent_id)
    q = search.strip().lower()
    apps = [
        _app(g, held, q) for g in groups.values() if not q or q in g.name.lower() or any(q in _text(t) for t in g.tools)
    ]
    if granted is True:
        apps = [a for a in apps if a["toolsGranted"]]
    elif granted is False:
        apps = [a for a in apps if _int(a["toolsGranted"]) < _int(a["toolsOffered"])]
    # The id last, so two apps of one name keep their order from page to page.
    apps.sort(key=lambda a: (not a["connected"], str(a["name"]).lower(), str(a["id"])))
    offset, _ = options_window(cursor, limit)
    return ok(options_page(options_cut(apps, offset, limit), offset, limit))


@router.get("/{agent_id}/tool-apps/{app_id}/tools", response_model=Envelope[AppToolsPage])
async def app_tools(
    rt: Rt,
    p: Reader,
    agent_id: str,
    app_id: str,
    *,
    search: Annotated[str, Query(max_length=200)] = "",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    granted: bool | None = None,
) -> JSONResponse:
    """One app's tools the team added, searched by title, name and description, each marked with whether the agent
    holds it; `granted` keeps the held ones (`true`) or the rest (`false`). An app the team has no card or tool of
    answers 404."""
    groups, held = await _read(rt, p, agent_id)
    group = groups.get(app_id)
    if group is None:
        raise NotFound(f"App {app_id}")
    q = search.strip().lower()
    tools = [t for t in group.tools if (not q or q in _text(t)) and (granted is None or (t["id"] in held) == granted)]
    tools.sort(key=lambda t: (_label(t).lower(), t["id"]))
    rows: list[Json] = [
        {
            "id": t["id"],
            "label": _label(t),
            "description": t["description"],
            "access": t["access"],
            "requiresApproval": t["requiresApproval"],
            "approval": t["approval"],
            "granted": t["id"] in held,
        }
        for t in tools
    ]
    offset, _ = options_window(cursor, limit)
    return ok(options_page(options_cut(rows, offset, limit), offset, limit))
