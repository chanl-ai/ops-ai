"""The team's systems, one card each, for the console's Connections grid (c-580): a plugin the install offers or the
team turned on, a connection, or a tool module with no connection yet. Each card is joined here (its details, how many
tools use it, each environment's health) so the console never joins the module, connection and plugin lists itself.

A module that uses a connection is part of that connection's card, and a plugin's connection is part of the plugin's
card, so no system shows twice. Every read is the caller's team's, as the connection list's is."""

# No `from __future__ import annotations`: FastAPI resolves the `Depends(caller)` annotations at import.

from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ops_service_kit.http import Envelope, Out, ok

from .auth.kinds import BY_ID
from .callers import caller_in
from .connections.schemas import ConnectionHealth
from .connections.service import ConnectionService, environment_views
from .modules.directory import Directory
from .modules.routes import ERRORS
from .modules.service import Caller
from .plugins.host import PluginHost, module_id_of, per_environment
from .store.modules import ModuleStore
from .store.plugin_app_keys import PluginAppKeys


class SystemEnvironment(Out):
    label: str
    set: bool
    health: ConnectionHealth | None = None


class PluginSetting(Out):
    name: str
    label: str
    default: str | None = None
    secret: bool = False
    # Each environment keeps its own value (a sandbox signs in elsewhere), so the dialog asks for it per environment.
    per_environment: bool = False
    # Fixed by the platform admin for every team; shown, never typed.
    locked: bool = False


class SystemPlugin(Out):
    install_on: bool
    team_on: bool
    # Whether an account admin set up the platform's app, so a team may sign in with no app of its own.
    platform_app: bool
    # The sign-in kinds the plugin offers, the first the default; a team's connection keeps the one it chose first.
    kinds: list[str]
    sign_in: list[str]
    scopes: list[str]
    # The settings a team types, in the manifest's order; those read from the token at sign-in are left out.
    settings: list[PluginSetting]
    # The sign-in kind's fields the plugin fixes itself (how its key is sent), so a team is never asked for them.
    fixed: list[str]


class SystemCard(Out):
    id: str
    kind: Literal["plugin", "connection", "module"]
    name: str
    logo: str | None = None
    category: str | None = None
    description: str | None = None
    docs_url: str | None = None
    tools_count: int
    auth_kind: str | None = None
    kind_label: str | None = None
    connection_id: str | None = None
    plugin_id: str | None = None
    module_ids: list[str]
    status: str | None = None
    environments: dict[str, SystemEnvironment]
    may_manage: bool
    plugin: SystemPlugin | None = None


def _environments(conn: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    envs = cast(dict[str, dict[str, Any]], (conn or {}).get("environments") or {})
    return {
        e["id"]: {"label": e["label"], "set": e["id"] in envs, "health": (envs.get(e["id"]) or {}).get("health")}
        for e in environment_views()
    }


class Systems:
    def __init__(
        self,
        connections: ConnectionService,
        modules: ModuleStore,
        plugins: PluginHost | None = None,
        app_keys: PluginAppKeys | None = None,
    ) -> None:
        self.connections = connections
        self.modules = modules
        self.plugins = plugins
        self.app_keys = app_keys

    async def cards(self, who: Caller) -> list[dict[str, Any]]:
        conns = await self.connections.team_rows(who)
        may = self.connections.may_manage(who)
        by_id = {str(c["id"]): c for c in conns}
        team = who.team.id
        modules = [m for m in await self.modules.all(who.tenant_id) if m.get("team_id") in (team, None)]
        ops = {str(m["id"]): len(m.get("operations") or []) for m in modules}
        cards: list[dict[str, Any]] = []
        taken: set[str] = set()
        if self.plugins is not None:
            await self.plugins.ensure(who.tenant_id, self.connections.clock())
            bindings = await self.plugins.bindings.of_team(who.tenant_id, team)
            for pid, plugin in sorted(self.plugins.plugins.items()):
                m = plugin.manifest
                b = bindings.get(pid) or {}
                install_on = await self.plugins.switches.on(who.tenant_id, pid)
                if not install_on and not b:
                    continue
                conn = by_id.get(str(b.get("connection_id") or ""))
                if conn is not None:
                    taken.add(str(conn["id"]))
                platform = bool(await self.plugins.switches.app_client_id(who.tenant_id, pid)) and (
                    self.app_keys is not None and await self.app_keys.held(who.tenant_id, pid)
                )
                locked = await self.plugins.switches.locked(who.tenant_id, pid)
                own = per_environment(m)
                settings = [
                    {
                        "name": k,
                        "label": s.title or k,
                        "default": None if s.default is None else str(s.default),
                        "secret": s.secret,
                        "perEnvironment": k in own,
                        "locked": k in locked,
                    }
                    for k, s in m.settings.items()
                    if not s.from_token
                ]
                cards.append(
                    {
                        "id": f"plugin:{pid}",
                        "kind": "plugin",
                        "name": m.title,
                        "logo": m.display.logo,
                        "category": m.display.category,
                        "description": m.display.description,
                        "docsUrl": m.display.docs_url,
                        "toolsCount": len(m.tools),
                        "authKind": m.connection.kinds[0],
                        "kindLabel": BY_ID[m.connection.kinds[0]].label if m.connection.kinds[0] in BY_ID else None,
                        "connectionId": conn["id"] if conn else None,
                        "pluginId": pid,
                        "moduleIds": [module_id_of(m)],
                        "status": conn["status"] if conn else None,
                        "environments": _environments(conn),
                        "mayManage": may,
                        "plugin": {
                            "installOn": install_on,
                            "teamOn": bool(b.get("enabled")),
                            "platformApp": platform,
                            "kinds": list(m.connection.kinds),
                            "signIn": list(m.connection.sign_in),
                            "scopes": [sc.label or sc.id for sc in m.connection.scopes],
                            "settings": settings,
                            "fixed": sorted(("placement", "name") if m.connection.api_key is not None else ()),
                        },
                    }
                )
        for conn in conns:
            if str(conn["id"]) in taken:
                continue
            used = [str(u["id"]) for u in cast(list[dict[str, Any]], conn.get("used_by") or [])]
            kind = BY_ID.get(str(conn["auth_kind"]))
            cards.append(
                {
                    "id": str(conn["id"]),
                    "kind": "connection",
                    "name": conn["name"],
                    "category": conn.get("category"),
                    "description": conn.get("description"),
                    "docsUrl": conn.get("docs_url"),
                    "toolsCount": sum(ops.get(u, 0) for u in used),
                    "authKind": conn["auth_kind"],
                    "kindLabel": kind.label if kind else None,
                    "connectionId": conn["id"],
                    "moduleIds": used,
                    "status": conn["status"],
                    "environments": _environments(conn),
                    "mayManage": may,
                }
            )
        for m in modules:
            if m.get("connection_id") or str(m.get("template_id") or "").startswith("plugin:"):
                continue
            cards.append(
                {
                    "id": f"module:{m['id']}",
                    "kind": "module",
                    "name": m["display_name"],
                    "description": m.get("description") or None,
                    "toolsCount": ops.get(str(m["id"]), 0),
                    "moduleIds": [str(m["id"])],
                    "environments": _environments(None),
                    "mayManage": may,
                }
            )
        return sorted(cards, key=lambda c: str(c["name"]).lower())


def systems_router(systems: Systems, directory: Directory) -> APIRouter:
    caller = caller_in(directory)
    r = APIRouter(tags=["connections"], responses=ERRORS)

    @r.get("/v1/systems", response_model=Envelope[list[SystemCard]])
    async def list_systems(who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The team's systems, one card each, joined for the Connections grid (c-580)."""
        return ok([SystemCard(**c).model_dump(by_alias=True) for c in await systems.cards(who)])

    return r
