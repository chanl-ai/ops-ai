"""The team's systems, one card each, for the console's Connections grid (c-580): a plugin the install offers or the
team turned on, a connection, or a tool module with no connection yet. Each card is joined here (its details, how many
tools use it, each environment's health) so the console never joins the module, connection and plugin lists itself.

A module that uses a connection is part of that connection's card, and a plugin's connection is part of the plugin's
card, so no system shows twice. Every read is the caller's team's, as the connection list's is."""

# No `from __future__ import annotations`: FastAPI resolves the `Depends(caller)` annotations at import.

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_service_kit.errors import NotFound
from ops_service_kit.http import Envelope, Out, ok

from .auth.kinds import BY_ID, kind_of
from .callers import caller_in
from .connections.records import CONNECTED, account_state, deciding_environment, shown_status, state_reason
from .connections.schemas import ConnectionDetail, ConnectionHealth
from .connections.service import ConnectionService, own_key
from .defaults import ensure_defaults
from .environments import connection_views
from .modules.directory import Directory
from .modules.routes import ERRORS
from .modules.schemas import ToolCallRow
from .modules.seed import BUILT_IN, TOOL_ORIGIN, template_of
from .modules.service import Caller, ModuleService
from .plugins.host import PluginHost, fixed_fields, module_id_of, per_environment
from .plugins.templates import view_of
from .store.modules import ModuleStore
from .store.plugin_app_keys import PluginAppKeys
from .store.team_defaults import TeamDefaults

AccountState = Literal["connected", "not_signed_in", "expired", "refused", "revoked"]


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
    kind: Literal["plugin", "connection", "module", "builtin"]
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
    # The team account's state (c-616): connected, not_signed_in, expired, refused or revoked; none for an app the
    # team has not turned on and a module with no connection.
    state: AccountState | None = None
    environments: dict[str, SystemEnvironment]
    may_manage: bool
    plugin: SystemPlugin | None = None
    # A built-in app's console page, where it is managed (its knowledge bases, its mailboxes).
    href: str | None = None


# An app credential's status, from the last Test with my account (connections.service check_credential).
CredentialStatus = Literal["working", "not_tested", "failing"]
CHECKED = "credential_checked"


class AppCredential(Out):
    """How one of the team's apps signs in (c-616 C0): Ops AI's app or the team's own OAuth client, never its secret."""

    # The account the credential is set on; the Credentials page opens it.
    id: str
    name: str
    app: str
    app_name: str
    type: Literal["ops_ai", "own"]
    permissions: list[str]
    # Accounts signed in through it in the environment that decides the app: the team account and each person's.
    accounts: int
    status: CredentialStatus
    created: str


class AppTool(Out):
    name: str
    title: str
    access: str


class AppSkill(Out):
    kind: str
    id: str
    title: str


class AppMe(Out):
    """The caller's own sign-in on the app's account: Connect my account, or Connected as."""

    connected: bool
    account: str | None = None


class AppAccount(Out):
    """One of the team's accounts of the app (c-608): the default is the one calls use unless they name another."""

    id: str
    name: str
    default: bool
    status: str
    status_detail: str | None = None
    # Connected only after a sign-in or a passing test (c-616), as the card's.
    state: AccountState
    # Why it is refused or expired (c-616 S12): the system's words, or the day the sign-in ended.
    state_reason: str | None = None
    # Whether the caller has signed in to this account themselves, and as whom.
    mine: bool = False
    account: str | None = None
    # The caller's own default among their sign-ins to the app (c-608).
    pinned: bool = False


class AppPage(Out):
    """One app's page (c-607), joined here: its card, its account's connection, the caller's own sign-in, how many
    people signed in, its tools, the plugin's skills and the latest runs of its tools."""

    card: SystemCard
    connection: ConnectionDetail | None = None
    me: AppMe
    people_count: int
    # The team's accounts of the app, the default first; one unless several_accounts is on.
    accounts: list[AppAccount] = Field(default_factory=list[AppAccount])
    tools: list[AppTool]
    skills: list[AppSkill]
    usage: list[ToolCallRow]


def _built_in(app: dict[str, Any], module: dict[str, Any]) -> list[str]:
    """The app's operations the module holds: all of them, or the ones the app names."""
    held = [str(o["name"]) for o in cast(list[dict[str, Any]], module.get("operations") or [])]
    wanted = app.get("operations")
    return [n for n in held if wanted is None or n in wanted]


def _environments(conn: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    envs = cast(dict[str, dict[str, Any]], (conn or {}).get("environments") or {})
    return {
        e["id"]: {"label": e["label"], "set": e["id"] in envs, "health": (envs.get(e["id"]) or {}).get("health")}
        for e in connection_views()
    }


class Systems:
    def __init__(
        self,
        connections: ConnectionService,
        modules: ModuleStore,
        plugins: PluginHost | None = None,
        app_keys: PluginAppKeys | None = None,
        calls: ModuleService | None = None,
    ) -> None:
        self.connections = connections
        self.modules = modules
        self.plugins = plugins
        self.app_keys = app_keys
        # The call log, for an app's Usage tab; without it the page lists no runs.
        self.calls = calls

    async def states(self, tenant_id: str, conns: list[dict[str, Any]]) -> dict[str, tuple[str, str, str | None]]:
        """Each connection's (state, status, why) from its team account's token, read in one query (c-616)."""
        tokens = await self.connections.store.team_tokens(tenant_id, [str(c["id"]) for c in conns])
        now = self.connections.clock()
        out: dict[str, tuple[str, str, str | None]] = {}
        for c in conns:
            token = (tokens.get(str(c["id"])) or {}).get(deciding_environment(c))
            state = account_state(c, token, now)
            out[str(c["id"])] = (state, shown_status(c, state, now), state_reason(c, token, state))
        return out

    async def cards(self, who: Caller, *, listed: bool = False, builtins: bool = True) -> list[dict[str, Any]]:
        """Every app the team has; `listed`: only the Apps grid's (owner, 2026-11-01), the plugins and the apps a person
        added. A built-in app has its own menu, and a connection made to hold a custom tool's address (origin "tool")
        or a module with none is reached from its tool, so neither is listed; their pages still answer. `builtins` keeps
        the built-in apps in a listed answer, for a picker where they belong (approvals: a mailbox reply)."""
        if builtins or not listed:
            # A team made before team.created reached this service has no defaults row, so the start-up catch-up never
            # finds it: listing its built-in apps provisions them, as a first tool lookup does (c-616).
            await ensure_defaults(
                self.modules, TeamDefaults(self.modules.engine), tenant_id=who.tenant_id, team_id=who.team.id,
                at=datetime.now(UTC),
            )  # fmt: skip
        conns = await self.connections.team_rows(who)
        may = self.connections.may_manage(who)
        by_id = {str(c["id"]): c for c in conns}
        states = await self.states(who.tenant_id, conns)
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
                    if not s.at_sign_in
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
                        "status": states[str(conn["id"])][1] if conn else None,
                        "state": states[str(conn["id"])][0] if conn else None,
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
                            "fixed": fixed_fields(m),
                        },
                    }
                )
        for conn in conns:
            if str(conn["id"]) in taken or (listed and conn.get("origin") == TOOL_ORIGIN):
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
                    "status": states[str(conn["id"])][1],
                    "state": states[str(conn["id"])][0],
                    "environments": _environments(conn),
                    "mayManage": may,
                }
            )
        built: set[str] = set()
        for app in BUILT_IN:
            # The team's provisioned copy (c-616) when it has one; else the module of the app's older name. A module
            # bound to a connection is that connection's: it is served by the system, not by the platform.
            own = [m for m in modules if m.get("template_id") == template_of(app)]
            named = own or [m for m in modules if m["name"] == app["module"] and not m.get("connection_id")]
            held = [(m, _built_in(app, m)) for m in named]
            held = [(m, names) for m, names in held if names]
            if not held:
                continue
            built |= {str(m["id"]) for m, _ in held}
            if listed and not builtins:
                continue
            cards.append(
                {
                    "id": f"builtin:{app['id']}",
                    "kind": "builtin",
                    "name": app["name"],
                    "category": "Built in",
                    "description": app["description"],
                    "toolsCount": sum(len(names) for _, names in held),
                    "kindLabel": "No sign-in",
                    "moduleIds": [str(m["id"]) for m, _ in held],
                    "status": "connected",
                    "state": CONNECTED,
                    "environments": _environments(None),
                    "mayManage": may,
                    "href": app["href"],
                }
            )
        for m in modules:
            if m.get("connection_id") or str(m.get("template_id") or "").startswith("plugin:") or str(m["id"]) in built:
                continue
            if listed:
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


async def app_credentials(systems: Systems, who: Caller) -> list[dict[str, Any]]:
    """Each app the team set up that signs in through an OAuth app, with how (c-616 C0): only a person who manages the
    team's apps reads them, and no secret is read."""
    systems.connections.check(who, "manage", what="app credentials")
    store = systems.connections.store
    rows: list[dict[str, Any]] = []
    for card in await systems.cards(who):
        connection_id = card.get("connectionId")
        conn = await store.get(who.tenant_id, str(connection_id)) if connection_id else None
        if conn is None or kind_of(str(conn["auth_kind"])).field("clientId") is None:
            continue
        env = deciding_environment(conn)
        envs = cast(dict[str, dict[str, Any]], conn.get("environments") or {})
        held = envs.get(env) or {}
        scopes = str(cast(dict[str, Any], held.get("settings") or {}).get("scopes") or "").split()
        plugin = systems.plugins.plugins.get(str(card.get("pluginId"))) if systems.plugins else None
        if not scopes and plugin is not None:
            scopes = [sc.id for sc in plugin.manifest.connection.scopes]
        tokens = [t for t in await store.tokens(who.tenant_id, str(conn["id"])) if t["environment"] == env]
        checked = next((a for a in await store.audit(who.tenant_id, str(conn["id"])) if a["action"] == CHECKED), None)
        said = str(cast(dict[str, Any], (checked or {}).get("detail") or {}).get("status") or "")
        rows.append(
            {
                "id": str(conn["id"]),
                "name": str(conn.get("account_name") or conn["name"]),
                "app": str(card["id"]),
                "appName": str(card["name"]),
                "type": "ops_ai" if held.get("platform_app") else "own",
                "permissions": scopes,
                "accounts": len(tokens),
                "status": "working" if said == "ok" else "failing" if said == "failed" else "not_tested",
                "created": conn["created_at"].isoformat(),
            }
        )
    return rows


async def app_page(systems: Systems, who: Caller, app_id: str) -> dict[str, Any]:
    """An app's page as one answer: a card of the caller's team only, so another team's app is not found."""
    card = next((c for c in await systems.cards(who) if c["id"] == app_id), None)
    if card is None:
        raise NotFound(f"App {app_id}")
    detail = await systems.connections.detail(who, str(card["connectionId"])) if card.get("connectionId") else None
    mine = own_key(who)
    signed = [p for p in (detail or {}).get("people", []) if p["personId"] == mine]
    people = (
        {str(p["person_id"]) for p in await systems.connections.store.people(who.tenant_id, str(card["connectionId"]))}
        if card.get("connectionId")
        else set[str]()
    )
    tools: list[dict[str, Any]] = []
    usage: list[dict[str, Any]] = []
    app = next((a for a in BUILT_IN if f"builtin:{a['id']}" == card["id"]), None)
    for module_id in card["moduleIds"]:
        module = await systems.modules.get(who.tenant_id, module_id)
        if module is None:
            continue
        mine_ops = set(_built_in(app, module)) if app else None
        for op in cast(list[dict[str, Any]], module.get("operations") or []):
            name = str(op["name"])
            if mine_ops is not None and name not in mine_ops:
                continue
            title = systems.plugins.title_of(module, name) if systems.plugins else None
            tools.append({"name": name, "title": title or name, "access": str(op["access"])})
        if systems.calls is not None:
            ran = await systems.calls.executions(
                who, page=1, page_size=20, tool=None, module_id=module_id, thread_id=None, decision=None
            )
            usage += list(ran["data"])
    accounts = await _accounts(systems, who, card, detail)
    skills: list[dict[str, Any]] = []
    plugin = (
        systems.plugins.plugins.get(str(card.get("pluginId"))) if systems.plugins and card.get("pluginId") else None
    )
    if plugin is not None:
        skills = [{"kind": t.kind, "id": t.id, "title": view_of(plugin, t)["title"]} for t in plugin.manifest.templates]
    return {
        "card": card,
        "connection": detail,
        "me": {"connected": bool(signed), "account": signed[0].get("account") if signed else None},
        "peopleCount": len(people),
        "accounts": accounts,
        "tools": tools,
        "skills": skills,
        "usage": usage,
    }


async def _accounts(
    systems: Systems, who: Caller, card: dict[str, Any], detail: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """The app's accounts for the page, the default (the binding's) first; with several_accounts off, that one only."""
    if detail is None:
        return []
    default = str(card["connectionId"])
    store = systems.connections.store
    stored = [r for r in [await store.get(who.tenant_id, default)] if r is not None]
    host = systems.plugins
    if host is not None and host.accounts and card.get("pluginId"):
        stored += [
            a
            for a in await store.accounts(who.tenant_id, who.team.id, str(card["pluginId"]))
            if str(a["id"]) != default
        ]
    states = await systems.states(who.tenant_id, stored)
    rows: list[dict[str, Any]] = [
        {
            "id": str(a["id"]),
            "name": (detail.get("accountName") or detail["name"])
            if str(a["id"]) == default
            else a.get("account_name") or a["name"],
            **_state(a, states[str(a["id"])]),
        }
        for a in stored
    ]
    mine = own_key(who)
    signed = {
        str(t["connection_id"]): t
        for t in await systems.connections.store.own_sign_ins(
            who.tenant_id, mine, [r["id"] for r in rows], "production"
        )
    }
    return [
        {
            **r,
            "default": r["id"] == default,
            "mine": r["id"] in signed,
            "account": (signed.get(r["id"]) or {}).get("account"),
            "pinned": bool((signed.get(r["id"]) or {}).get("pinned")),
        }
        for r in rows
    ]


def _state(conn: dict[str, Any], state: tuple[str, str, str | None]) -> dict[str, Any]:
    return {"state": state[0], "status": state[1], "statusDetail": conn.get("status_detail"), "stateReason": state[2]}


def systems_router(systems: Systems, directory: Directory) -> APIRouter:
    caller = caller_in(directory)
    r = APIRouter(tags=["connections"], responses=ERRORS)

    @r.get("/v1/systems", response_model=Envelope[list[SystemCard]])
    async def list_systems(  # pyright: ignore[reportUnusedFunction]
        who: Annotated[Caller, Depends(caller)], include: Annotated[Literal["builtin"] | None, Query()] = None
    ) -> JSONResponse:
        """The team's apps for the Apps grid (c-580): its plugins and the apps a person added. `include=builtin` adds
        the built-in apps, for the approval policy's app picker (owner, 2026-11-01)."""
        cards = await systems.cards(who, listed=True, builtins=include == "builtin")
        return ok([SystemCard(**c).model_dump(by_alias=True) for c in cards])

    @r.get("/v1/app-credentials", response_model=Envelope[list[AppCredential]])
    async def list_app_credentials(who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The team's app credentials, for the Credentials page under Apps (c-616 C0): each app's type, permissions,
        accounts and the last Test with my account. Team admins only; no secret."""
        return ok([AppCredential(**c).model_dump(by_alias=True) for c in await app_credentials(systems, who)])

    @r.get("/v1/apps/{app_id}", response_model=Envelope[AppPage])
    async def get_app(app_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """One app's page (c-607): its card, account, the caller's own sign-in, tools, skills and latest runs."""
        return ok(AppPage(**await app_page(systems, who, app_id)).model_dump(by_alias=True))

    return r
