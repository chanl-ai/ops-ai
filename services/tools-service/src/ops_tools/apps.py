"""The team's apps, one card each, for the console's Apps grid, and the `/v1/apps` routes: a plugin the
install offers, a custom app a builder added, a built-in app, or a tool module with no app yet. Each card is joined here
(its details, how many tools use it, its account's state) so the console never joins the module, account and plugin
lists itself.

An app's accounts are its `connections` rows (`app_id`): a plugin's binding names its default account, and a custom
app's first account is the app. A module that uses an account is part of that app's card, and a plugin's accounts are
part of the plugin's card, so no app shows twice. Every read is the caller's team's."""

# No `from __future__ import annotations`: FastAPI resolves the `Depends(caller)` annotations at import.

import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_identity import ActingPerson
from ops_plugin_sdk import Plugin
from ops_plugin_sdk.manifest import Setting
from ops_plugin_sdk.versions import tools_of
from ops_service_kit.errors import Conflict, NotFound, ServiceUnavailable, ValidationFailed
from ops_service_kit.http import Envelope, Out, ok

from .auth.kinds import BY_ID, kind_of
from .callers import caller_in
from .connections.records import (
    CONNECTED,
    account_state,
    default_sign_in,
    person_state,
    shown_status,
    state_reason,
    team_test,
)
from .connections.schemas import AccountDetail, AccountIn, AccountTest, ConnectionHealth, NewAppIn
from .connections.service import ConnectionService, own_key
from .defaults import ensure_defaults
from .modules.directory import Directory
from .modules.routes import ERRORS
from .modules.schemas import In, ToolCallRow
from .modules.seed import BUILT_IN, TOOL_ORIGIN, template_of, tool_title
from .modules.service import Caller, ModuleService
from .modules.tool_users import ToolUsers
from .plugins.host import PluginHost, fixed_fields, module_id_of, per_account, plugin_id_of
from .plugins.routes import PluginAccounts, TeamPluginIn
from .plugins.templates import view_of
from .store.connections import plugin_app, plugin_of
from .store.modules import ModuleStore
from .store.team_defaults import TeamDefaults

AccountState = Literal["connected", "not_signed_in", "expired", "refused", "revoked"]


class SettingChoice(Out):
    """One value the setting takes, in the system's words; `test_account` starts the Test account switch on."""

    # As the manifest types it, so the value sent back is the one the check compares.
    value: bool | int | float | str
    label: str
    hint: str = ""
    test_account: bool = False


class SettingOther(Out):
    """A host typed in place of a choice: the value is `value` with `{host}` replaced, and the host must end in one of
    `hosts`; a host ending in one of `test_account_hosts` starts the Test account switch on."""

    label: str
    hint: str = ""
    placeholder: str = ""
    value: str
    hosts: list[str]
    test_account_hosts: list[str] = Field(default_factory=list[str])


class PluginSetting(Out):
    name: str
    label: str
    default: str | None = None
    secret: bool = False
    # Each account keeps its own value (a sandbox signs in elsewhere), so the dialog asks for it per account.
    per_account: bool = False
    # Fixed by the install for every team (plugin_locked); shown, never typed.
    locked: bool = False
    # The only values it takes, and a host typed in place of one; none for a setting that takes any value.
    choices: list[SettingChoice] | None = None
    other: SettingOther | None = None
    # Held by the app credential the account signs in with (the app registration's), not by the account.
    credential: bool = False


class SystemPlugin(Out):
    team_on: bool
    # Whether the install has Ops AI's own app for the plugin, so a team may sign in with no app of its own.
    platform_app: bool
    # The sign-in kinds the plugin offers, the first the default; a team's account keeps the one it chose first.
    kinds: list[str]
    sign_in: list[str]
    scopes: list[str]
    # The settings a team types, in the manifest's order; those read from the token at sign-in are left out.
    settings: list[PluginSetting]
    # The team's settings as a person may read them: a secret one never, even as its reference.
    values: dict[str, Any] = Field(default_factory=dict[str, Any])
    # The sign-in kinds' fields the plugin fixes itself (how its key is sent), so a team is never asked for them.
    fixed: list[str]
    # The plugin's tools the team's version has, by operation name.
    tools: list[str] = Field(default_factory=list[str])
    # The version this team runs (with plugin_updates on), and whether the installed one differs from it.
    team_version: str | None = None
    update_available: bool = False


AppState = Literal["connected", "test_failed", "needs_sign_in", "not_installed", "removed"]
REMOVED = "This app is no longer installed, so its tools are off. An admin installs it again to turn them back on."


class CardCredential(Out):
    # The team's app credential's id (its page under Credentials); none on Ops AI's app.
    id: str | None = None
    name: str
    type: Literal["ops_ai", "own"]


class SystemCard(Out):
    id: str
    kind: Literal["plugin", "connection", "module", "builtin"]
    name: str
    logo: str | None = None
    category: str | None = None
    description: str | None = None
    docs_url: str | None = None
    tools_count: int
    # The team's accounts of the app (its team account, sandbox and named ones), counted here for the card.
    accounts_count: int = 0
    auth_kind: str | None = None
    kind_label: str | None = None
    # The app's default account: the one a live call signs in with unless it names another.
    connection_id: str | None = None
    plugin_id: str | None = None
    # The app's sandbox account, which test runs use; none when it has none.
    sandbox_id: str | None = None
    module_ids: list[str]
    status: str | None = None
    # The default account's state: connected, not_signed_in, expired, refused or revoked; none for an app the
    # team has not turned on and a module with no account.
    state: AccountState | None = None
    may_manage: bool
    # Whether the install's own OAuth client signs this app in, so a team types no client id or secret.
    managed_client: bool = False
    plugin: SystemPlugin | None = None
    # A built-in app's console page, where it is managed (its knowledge bases, its mailboxes).
    href: str | None = None
    # The card's one state for the caller, worked out here so no screen derives it: connected, test_failed (signed in,
    # its test then failed), needs_sign_in, not_installed (not turned on for the team), or removed (turned on, then
    # taken off the install); with why when not connected.
    app_state: AppState
    app_state_reason: str | None = None
    # Whose OAuth app the card's account signs in with; none for an app that signs in without one.
    credential: CardCredential | None = None
    # Who signs in on the card's account: the team account, each person, or each person with the team's as backup.
    sign_in: Literal["team", "person", "person_or_team"] | None = None


# An app credential's status, from the last Test with my account (connections.service check_credential).
CredentialStatus = Literal["working", "not_tested", "failing"]
CHECKED = "credential_checked"


class AppCredential(Out):
    """One OAuth client the team's apps sign in with: one of the team's own (app_credentials, made under Credentials)
    or Ops AI's app for an app whose accounts use it. Never its secret."""

    # The team's credential's id; `ops-ai:<app>` for Ops AI's app of one app.
    id: str
    name: str
    app: str
    app_name: str
    type: Literal["ops_ai", "own"]
    # The client id; none for Ops AI's app, which the install keeps.
    client_id: str | None = None
    permissions: list[str]
    # The team's accounts signing in with it.
    accounts: int
    status: CredentialStatus
    created: str | None = None
    created_by: str | None = None


class CredentialAccount(Out):
    """An account signing in with an app credential, as its page lists it."""

    id: str
    name: str
    sandbox: bool = False
    state: AccountState
    status: str
    state_reason: str | None = None
    # Who signs in on it: the team account, each person, or each person with the team's as backup.
    sign_in: Literal["team", "person", "person_or_team"]
    # When the team account last signed in; none before it has.
    connected_at: str | None = None


class AppCredentialDetail(AppCredential):
    accounts_list: list[CredentialAccount]
    # The address to register with the app's sign-in.
    redirect_uri: str | None = None
    updated: str | None = None


class AppCredentialIn(In):
    """The team's own OAuth app for one of its apps (the New app credential window); no account needed."""

    # The app as the Apps page names it: `plugin:<id>` for an app from a plugin, the account's id for a custom app.
    app: str = Field(min_length=1, max_length=200)
    # What the Credentials page lists it as; left out, "<app> credentials".
    name: str | None = Field(default=None, min_length=1, max_length=200)
    client_id: str = Field(min_length=1, max_length=500)
    # Left out for a public client, or one that proves itself with a signed assertion (each account's signing pair).
    client_secret: str | None = Field(default=None, min_length=1, max_length=2000)
    # The permissions to ask for, among the app's own; left out, all of them. A plugin's required ones are always asked.
    scopes: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(default=None, max_length=100)


class CredentialSecretIn(In):
    client_secret: str = Field(min_length=1, max_length=2000)


class ToolUser(Out):
    id: str
    name: str


class ToolUsedBy(Out):
    agents: list[ToolUser]
    workflows: list[ToolUser]


class AppTool(Out):
    name: str
    title: str
    access: str
    # The team's agents granted it and workflows with a step that calls it, from agents-service; none when this
    # service cannot ask (no agents-service wired) or agents-service did not answer.
    used_by: ToolUsedBy | None = None


class AppSkill(Out):
    kind: str
    id: str
    title: str


class AppMe(Out):
    """The caller's own sign-in on the app's account: Connect my account, or Connected as."""

    connected: bool
    account: str | None = None


class AppAccount(Out):
    """One of the team's accounts of the app: the default is the one live calls use unless they name another,
    and a sandbox one is what test runs use."""

    id: str
    name: str
    default: bool
    sandbox: bool
    status: str
    status_detail: str | None = None
    # Connected only after a sign-in or a passing test, as the card's.
    state: AccountState
    # Why it is refused or expired: the system's words, or the day the sign-in ended.
    state_reason: str | None = None
    # Whether the caller has signed in to this account themselves, and as whom.
    mine: bool = False
    account: str | None = None
    # The last test, run right after each sign-in: the caller's own on an account each person signs in to, else the
    # team account's. A failed one warns on the row; the account stays connected.
    test: AccountTest | None = None
    health: ConnectionHealth | None = None


class AppPerson(Out):
    """One person's own sign-in on one of the app's accounts, for the app page's People tab: a team admin reads
    everyone's, anyone else their own."""

    person_id: str
    # Whether it is the caller's own.
    mine: bool
    # Who the system says signed in, when it says.
    account: str | None = None
    # The team account it is on, by its id and name.
    account_id: str
    account_name: str
    since: str | None = None
    state: Literal["connected", "expired", "refused"]
    # The test run right after the sign-in failed: the system's words. The sign-in stays connected.
    test_failed: str | None = None
    # Whether calls naming no account use this sign-in for the person: their pinned one, else their newest the system
    # has not refused. None while they hold only one they could use, or on a sandbox account, since nothing is chosen.
    default: bool | None = None


class AppPage(Out):
    """One app's page, joined here: its card, its default account, the caller's own sign-in, how many people
    signed in, its accounts, its tools, the plugin's skills and the latest runs of its tools."""

    card: SystemCard
    connection: AccountDetail | None = None
    me: AppMe
    people_count: int
    # The team's accounts of the app, the default first.
    accounts: list[AppAccount] = Field(default_factory=list[AppAccount])
    # Each person's own sign-in on the app's accounts, newest first.
    people: list[AppPerson] = Field(default_factory=list[AppPerson])
    tools: list[AppTool]
    skills: list[AppSkill]
    usage: list[ToolCallRow]


def setting_offer(s: Setting) -> dict[str, Any]:
    """A setting's choices and typed host as the Connect window draws them; empty for one that takes any value."""
    out: dict[str, Any] = {}
    if s.choices:
        out["choices"] = [
            {"value": c.value, "label": c.label, "hint": c.hint, "testAccount": c.test_account} for c in s.choices
        ]
    if s.other is not None:
        o = s.other
        out["other"] = {
            "label": o.label, "hint": o.hint, "placeholder": o.placeholder, "value": o.value, "hosts": list(o.hosts),
            "testAccountHosts": list(o.test_account_hosts),
        }  # fmt: skip
    return out


def _built_in(app: dict[str, Any], module: dict[str, Any]) -> list[str]:
    """The app's operations the module holds: all of them, or the ones the app names."""
    held = [str(o["name"]) for o in cast(list[dict[str, Any]], module.get("operations") or [])]
    wanted = app.get("operations")
    return [n for n in held if wanted is None or n in wanted]


class Apps:
    def __init__(
        self,
        connections: ConnectionService,
        modules: ModuleStore,
        plugins: PluginHost | None = None,
        calls: ModuleService | None = None,
        users: ToolUsers | None = None,
    ) -> None:
        self.connections = connections
        # Who uses each of an app's tools (agents-service), for the app page's Tools tab.
        self.users = users
        self.modules = modules
        self.plugins = plugins
        # A plugin's turn-on and accounts, when the install has plugins.
        self.plugin_accounts = PluginAccounts(plugins, connections) if plugins is not None else None
        # The call log, for an app's Usage tab; without it the page lists no runs.
        self.calls = calls

    async def states(self, tenant_id: str, conns: list[dict[str, Any]]) -> dict[str, tuple[str, str, str | None]]:
        """Each account's (state, status, why) from its team account's token, read in one query."""
        tokens = await self.connections.store.team_tokens(tenant_id, [str(c["id"]) for c in conns])
        now = self.connections.clock()
        out: dict[str, tuple[str, str, str | None]] = {}
        for c in conns:
            token = tokens.get(str(c["id"]))
            state = account_state(c, token, now)
            out[str(c["id"])] = (state, shown_status(c, state, now), state_reason(c, token, state))
        return out

    async def cards(
        self, who: Caller, *, listed: bool = False, builtins: bool = True, person: str | None = None
    ) -> list[dict[str, Any]]:
        """Every app the team has; `listed`: only the Apps grid's (owner, 2026-11-01), the plugins and the apps a person
        added. A built-in app has its own menu, and an account made to hold a custom tool's address (origin "tool") or
        a module with none is reached from its tool, so neither is listed; their pages still answer. `builtins` keeps
        the built-in apps in a listed answer, for a picker where they belong (approvals: a mailbox reply)."""
        if builtins or not listed:
            # A team made before team.created reached this service has no defaults row, so the start-up catch-up never
            # finds it: listing its built-in apps provisions them, as a first tool lookup does.
            await ensure_defaults(
                self.modules, TeamDefaults(self.modules.engine), tenant_id=who.tenant_id, team_id=who.team.id,
                at=datetime.now(UTC),
            )  # fmt: skip
        conns = await self.connections.team_rows(who)
        may = self.connections.may_manage(who)
        by_id = {str(c["id"]): c for c in conns}
        sandboxes: dict[str, str] = {}
        accounts = Counter(str(c["app_id"]) for c in conns)
        for c in conns:
            if c.get("sandbox"):
                sandboxes.setdefault(str(c["app_id"]), str(c["id"]))
        states = await self.states(who.tenant_id, conns)
        team = who.team.id
        modules = [m for m in await self.modules.all(who.tenant_id) if m.get("team_id") in (team, None)]
        ops = {str(m["id"]): len(m.get("operations") or []) for m in modules}
        cards: list[dict[str, Any]] = []
        if self.plugins is not None:
            await self.plugins.ensure(who.tenant_id, self.connections.clock())
            bindings = await self.plugins.bindings.of_team(who.tenant_id, team)
            for pid, plugin in sorted(self.plugins.plugins.items()):
                m = plugin.manifest
                b = bindings.get(pid) or {}
                conn = by_id.get(str(b.get("connection_id") or ""))
                platform = self.connections.store.install_client(pid) is not None
                locked = self.plugins.locked_settings(pid)
                own = per_account(m)
                settings = [
                    {
                        "name": k,
                        "label": s.title or k,
                        "default": None if s.default is None else str(s.default),
                        "secret": s.secret,
                        "perAccount": k in own,
                        "locked": k in locked,
                        **setting_offer(s),
                        "credential": k in m.connection.credential_settings,
                    }
                    for k, s in m.settings.items()
                    if not s.at_sign_in
                ]
                decl = cast(dict[str, Any] | None, b.get("declarations")) if self.plugins.versions else None
                cards.append(
                    {
                        "id": plugin_app(pid),
                        "kind": "plugin",
                        "name": m.title,
                        "logo": m.display.logo,
                        "category": m.display.category,
                        "description": m.display.description,
                        "docsUrl": m.display.docs_url,
                        "toolsCount": len(m.tools),
                        "accountsCount": accounts[plugin_app(pid)],
                        "authKind": m.connection.kinds[0],
                        "kindLabel": BY_ID[m.connection.kinds[0]].label if m.connection.kinds[0] in BY_ID else None,
                        "connectionId": conn["id"] if conn else None,
                        "pluginId": pid,
                        "sandboxId": sandboxes.get(plugin_app(pid)),
                        "moduleIds": [module_id_of(m)],
                        "status": states[str(conn["id"])][1] if conn else None,
                        "state": states[str(conn["id"])][0] if conn else None,
                        "mayManage": may,
                        "managedClient": platform,
                        "plugin": {
                            "teamOn": bool(b.get("enabled")),
                            "platformApp": platform,
                            "kinds": list(m.connection.kinds),
                            "signIn": list(m.connection.sign_in),
                            "scopes": [sc.label or sc.id for sc in m.connection.scopes],
                            "settings": settings,
                            "values": self.plugin_accounts.team_values(
                                plugin, b, dict((conn or {}).get("plugin_settings") or {})
                            )
                            if self.plugin_accounts
                            else {},
                            "fixed": fixed_fields(m),
                            "tools": [m.operation(t) for t in tools_of(decl)]
                            if decl
                            else [m.operation(t.name) for t in m.tools],
                            "teamVersion": b.get("version") if self.plugins.versions else None,
                            "updateAvailable": self.plugins.versions
                            and bool(b.get("digest"))
                            and b.get("digest") != self.plugins.installed_digest(plugin),
                        },
                    }
                )
            # A plugin the team turned on that the install no longer holds keeps its card, so the team sees why its
            # tools stopped instead of finding its account listed as a custom app.
            for pid, b in sorted(bindings.items()):
                if pid in self.plugins.plugins or not b.get("enabled"):
                    continue
                conn = by_id.get(str(b.get("connection_id") or ""))
                row = next((md for md in modules if plugin_id_of(md) == pid), None)
                cards.append(
                    {
                        "id": plugin_app(pid),
                        "kind": "plugin",
                        # The account the plugin made carries its title, which outlives the manifest.
                        "name": str(row["display_name"]) if row else str(conn["name"]) if conn else pid,
                        "toolsCount": 0,
                        "connectionId": conn["id"] if conn else None,
                        "pluginId": pid,
                        "moduleIds": [str(row["id"])] if row else [],
                        "mayManage": may,
                    }
                )
        for conn in conns:
            # A custom app is its first account; its other accounts and every plugin's are part of their app's card.
            if conn["app_id"] != conn["id"] or (listed and conn.get("origin") == TOOL_ORIGIN):
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
                    "accountsCount": accounts[str(conn["id"])],
                    "authKind": conn["auth_kind"],
                    "kindLabel": kind.label if kind else None,
                    "connectionId": conn["id"],
                    "sandboxId": sandboxes.get(str(conn["id"])),
                    "moduleIds": used,
                    "status": states[str(conn["id"])][1],
                    "state": states[str(conn["id"])][0],
                    "mayManage": may,
                    "managedClient": False,
                }
            )
        built: set[str] = set()
        for app in BUILT_IN:
            # The team's provisioned copy when it has one; else the module of the app's older name. A module
            # bound to an account is that app's: it is served by the system, not by the platform.
            own_modules = [m for m in modules if m.get("template_id") == template_of(app)]
            named = own_modules or [m for m in modules if m["name"] == app["module"] and not m.get("connection_id")]
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
                    "mayManage": may,
                    "managedClient": False,
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
                    "mayManage": may,
                    "managedClient": False,
                }
            )
        await self._app_states(who, cards, by_id, person)
        return sorted(cards, key=lambda c: str(c["name"]).lower())

    async def _app_states(
        self, who: Caller, cards: list[dict[str, Any]], by_id: dict[str, dict[str, Any]], person: str | None
    ) -> None:
        """Each card's appState, appStateReason and credential, from the default account's team token and the own
        sign-ins of the caller, or of `person` when a service asks for one (acting for them), read once for every
        card."""
        ids = [str(c["connectionId"]) for c in cards if c.get("connectionId")]
        store = self.connections.store
        team_tokens = await store.team_tokens(who.tenant_id, ids)
        mine = person or own_key(who)
        own: dict[str, dict[str, Any]] = {}
        for t in await store.own_sign_ins(who.tenant_id, mine, ids):
            own.setdefault(str(t["connection_id"]), t)
        for c in cards:
            conn = by_id.get(str(c.get("connectionId") or ""))
            token = team_tokens.get(str(conn["id"])) if conn else None
            mine_row = own.get(str(conn["id"])) if conn else None
            c["appState"], c["appStateReason"] = app_state(c, conn, token, mine_row)
            c["credential"] = card_credential(conn)
            c["signIn"] = (conn.get("sign_in") or "team") if conn else None

    async def card(self, who: Caller, app_id: str) -> dict[str, Any]:
        found = next((c for c in await self.cards(who) if c["id"] == app_id), None)
        if found is None:
            raise NotFound(f"App {app_id}")
        return found

    async def add_custom(self, who: Caller, i: NewAppIn) -> dict[str, Any]:
        """A custom app, as its first account: by name, or an MCP server by its address."""
        if i.server_url is not None:
            return await self.connections.connect_mcp(who, i.model_dump())
        return await self.connections.create(who, i.model_dump())

    async def add_account(self, who: Caller, app_id: str, i: AccountIn) -> dict[str, Any]:
        """Another account of one of the team's apps: a plugin's from its definition, a custom app's with the app's
        sign-in kind and the kind's fields as given."""
        if plugin_of({"app_id": app_id}) is not None:
            if self.plugin_accounts is None:
                raise NotFound(f"App {app_id}")
            made = await self.plugin_accounts.add_account(who, app_id, i)
            return await self.connections.detail(who, made)
        app = await self.connections.account_of(who, app_id, app_id)
        kind = kind_of(str(app["auth_kind"]))
        plain = {k: v for k, v in i.credentials.items() if (f := kind.field(k)) is not None and not f.secret}
        secret = {k: v for k, v in i.credentials.items() if k not in plain}
        made = await self.connections.create(
            who,
            {
                "name": i.name,
                "app_id": app_id,
                "account_name": i.name,
                "sandbox": i.sandbox,
                "auth_kind": app["auth_kind"],
                "sign_in": i.sign_in or app.get("sign_in") or "team",
                "category": app.get("category"),
                "description": app.get("description"),
                "docs_url": app.get("docs_url"),
            },
        )
        if not plain and not secret:
            return made
        # The app's address is the account's unless the sandbox names its own.
        keys = {"baseUrl": dict(app["settings"] or {}).get("baseUrl"), **plain}
        return await self.connections.change(
            who,
            str(made["id"]),
            {"revision": made["revision"], "settings": {k: v for k, v in keys.items() if v}, "secret_values": secret},
        )


def app_state(
    card: dict[str, Any], conn: dict[str, Any] | None, team_token: dict[str, Any] | None, own: dict[str, Any] | None
) -> tuple[str, str | None]:
    """One card's state for the caller: signing in is what connects an account, and a failed test after it warns
    without disconnecting. On an app each person signs in to, it is the caller's own sign-in that counts."""
    if card["kind"] in ("builtin", "module"):
        return "connected", None
    plugin = cast(dict[str, Any] | None, card.get("plugin"))
    # Only a plugin card the install no longer loads is drawn without its manifest's details.
    if card["kind"] == "plugin" and plugin is None:
        return "removed", REMOVED
    if conn is None or (plugin is not None and not plugin.get("teamOn")) or not conn.get("settings"):
        return "not_installed", None
    if (conn.get("sign_in") or "team") == "person":
        if own is None or own.get("refused_at") is not None:
            return "needs_sign_in", "Sign in with your own account."
        test = cast(dict[str, Any] | None, own.get("test"))
    else:
        if card.get("state") != CONNECTED:
            return "needs_sign_in", state_reason(
                conn, team_token, str(card.get("state"))
            ) or "Sign in the team account."
        test = team_test(conn, team_token)
    if test is not None and test.get("status") == "failed":
        return "test_failed", str(test.get("message") or "The test after the sign-in failed.")
    return "connected", None


def card_credential(conn: dict[str, Any] | None) -> dict[str, Any] | None:
    """Whose OAuth app the card's account signs in with, as the Credentials page names it."""
    if conn is None or kind_of(str(conn["auth_kind"])).field("clientId") is None:
        return None
    name = str(conn.get("account_name") or conn["name"])
    own = not conn.get("platform_app")
    return {"id": conn.get("credential_id") if own else None, "name": name, "type": "own" if own else "ops_ai"}


OPS_AI = "ops-ai:"


def credential_secret(credential_id: str) -> str:
    """The team secret's name holding an app credential's client secret."""
    return f"APP_{credential_id.upper()}_CLIENT_SECRET"


def _status(audits: list[dict[str, Any]]) -> CredentialStatus:
    """The last Test with my account of any account on the credential: working, failing, or not tested."""
    checked = next((x for x in audits if x["action"] == CHECKED), None)
    said = str(cast(dict[str, Any], (checked or {}).get("detail") or {}).get("status") or "")
    return "working" if said == "ok" else "failing" if said == "failed" else "not_tested"


async def _row(
    apps: Apps, who: Caller, cred: dict[str, Any] | None, card: dict[str, Any], accounts: list[dict[str, Any]]
) -> dict[str, Any]:
    """One credential's row: the team's own (`cred`) or, with none, Ops AI's app of `card`'s app."""
    plugin = _plugin(apps, card)
    scopes = str((cred or {}).get("scopes") or "").split()
    if not scopes and plugin is not None:
        scopes = [sc.id for sc in plugin.manifest.connection.scopes]
    store = apps.connections.store
    audits = sorted(
        [x for a in accounts for x in await store.audit(who.tenant_id, str(a["id"]))],
        key=lambda x: x["at"],
        reverse=True,
    )
    own = cred is not None
    return {
        "id": str(cred["id"]) if own else f"{OPS_AI}{card['id']}",
        "name": str(cred["name"]) if own else "Ops AI's app",
        "app": str(card["id"]),
        "appName": str(card["name"]),
        "type": "own" if own else "ops_ai",
        "clientId": cred["client_id"] if own else None,
        "permissions": scopes,
        "accounts": len(accounts),
        "status": _status(audits),
        "created": cred["created_at"].isoformat() if own else None,
        "createdBy": cred["created_by"] if own else None,
    }


def _plugin(apps: Apps, card: dict[str, Any]) -> Plugin | None:
    return apps.plugins.plugins.get(str(card.get("pluginId"))) if apps.plugins and card.get("pluginId") else None


def _signs_in_with_client(conn: dict[str, Any]) -> bool:
    return kind_of(str(conn["auth_kind"])).field("clientId") is not None


async def add_app_credential(apps: Apps, who: Caller, i: AppCredentialIn) -> dict[str, Any]:
    """The team's own OAuth client for one of its apps, with no account: its secret is sealed as the team's, marked
    as the credential's, and an account picks the credential when it is connected (credentialId)."""
    apps.connections.check(who, "manage", what="app credentials")
    card = await apps.card(who, i.app)
    if card["kind"] not in ("plugin", "connection"):
        raise ValidationFailed(f"{card['name']} signs in with no OAuth app.", code="no_app_credential")
    plugin = _plugin(apps, card)
    scopes = i.scopes
    if plugin is not None:
        kinds = [kind_of(k) for k in plugin.manifest.connection.kinds]
        if not any(k.field("clientId") is not None for k in kinds):
            raise ValidationFailed(f"{card['name']} signs in with no OAuth app.", code="no_app_credential")
        offered = plugin.manifest.connection.scopes
        unknown = sorted(set(scopes or []) - {sc.id for sc in offered})
        if unknown:
            raise ValidationFailed(f"{card['name']} asks for no {', '.join(unknown)}.", details={"field": "scopes"})
        wanted = set(scopes) if scopes is not None else {sc.id for sc in offered}
        scopes = [sc.id for sc in offered if sc.required or sc.id in wanted]
    else:
        app = await apps.connections.account_of(who, str(card["id"]), str(card["connectionId"]))
        if not _signs_in_with_client(app):
            raise ValidationFailed(f"{card['name']} signs in with no OAuth app.", code="no_app_credential")
    now = apps.connections.clock()
    made = f"cred_{uuid.uuid4().hex[:12]}"
    secret = credential_secret(made) if i.client_secret else None
    if secret and not await apps.connections.secrets.create(
        who.tenant_id, who.team.id, secret, str(i.client_secret), actor=who.name, at=now, credential_id=made
    ):
        raise Conflict("Try again; that credential id was just taken.")
    await apps.connections.store.add_credential(
        {
            "tenant_id": who.tenant_id,
            "id": made,
            "team_id": who.team.id,
            "app_id": str(card["id"]),
            "name": (i.name or "").strip() or f"{card['name']} credentials",
            "client_id": i.client_id.strip(),
            "scopes": " ".join(scopes) if scopes is not None else None,
            "secret_name": secret,
            "created_by": who.name,
            "created_at": now,
            "updated_by": who.name,
            "updated_at": now,
        }
    )
    return await app_credential(apps, who, made)


async def replace_credential_secret(apps: Apps, who: Caller, credential_id: str, secret: str) -> dict[str, Any]:
    """A new client secret for the team's own app credential, sealed as the team's; the client id, permissions and
    every account on it stay, and the next sign-in of each uses it. Ops AI's app is the install's, never changed
    here."""
    apps.connections.check(who, "manage", what="app credentials")
    store = apps.connections.store
    cred = await store.credential(who.tenant_id, credential_id)
    if cred is None or cred["team_id"] != who.team.id:
        raise NotFound(f"App credential {credential_id}")
    now = apps.connections.clock()
    name = str(cred.get("secret_name") or credential_secret(credential_id))
    resolver = apps.connections.secrets
    if await resolver.rotate(who.tenant_id, who.team.id, name, secret, actor=who.name, at=now) is None:
        await resolver.create(
            who.tenant_id, who.team.id, name, secret, actor=who.name, at=now, credential_id=credential_id
        )
    await store.touch_credential(who.tenant_id, credential_id, actor=who.name, at=now)
    return await app_credential(apps, who, credential_id)


Held = tuple[dict[str, Any] | None, dict[str, Any], list[dict[str, Any]]]


async def _credentials(apps: Apps, who: Caller) -> list[Held]:
    """Each of the team's credentials with its app's card and its accounts, then Ops AI's app of each app whose
    accounts sign in with it; an app no longer listed is left out."""
    apps.connections.check(who, "manage", what="app credentials")
    store = apps.connections.store
    cards = {str(c["id"]): c for c in await apps.cards(who)}
    creds = await store.team_credentials(who.tenant_id, who.team.id)
    on = await store.credential_accounts(who.tenant_id, [str(c["id"]) for c in creds])
    out: list[Held] = []
    for cred in creds:
        card = cards.get(str(cred["app_id"]))
        if card is not None:
            out.append((cred, card, [a for a in on if a["credential_id"] == cred["id"]]))
    platform: dict[str, list[dict[str, Any]]] = {}
    for conn in await apps.connections.team_rows(who):
        if conn.get("platform_app") and _signs_in_with_client(conn):
            platform.setdefault(str(conn["app_id"]), []).append(conn)
    out += [(None, cards[app], accounts) for app, accounts in platform.items() if app in cards]
    return out


async def app_credentials(apps: Apps, who: Caller, app: str | None = None) -> list[dict[str, Any]]:
    """The team's app credentials and Ops AI's app of each app using it, of one app when `app` is given: only a person
    who manages the team's apps reads them, and no secret is read."""
    held = [x for x in await _credentials(apps, who) if app is None or x[1]["id"] == app]
    return [await _row(apps, who, cred, card, accounts) for cred, card, accounts in held]


async def app_credential(apps: Apps, who: Caller, credential_id: str) -> dict[str, Any]:
    """One credential's page: its row, and each account signing in with it with its state, joined here."""
    found = next(
        (
            x
            for x in await _credentials(apps, who)
            if (str(x[0]["id"]) if x[0] else f"{OPS_AI}{x[1]['id']}") == credential_id
        ),
        None,
    )
    if found is None:
        raise NotFound(f"App credential {credential_id}")
    cred, card, accounts = found
    states = await apps.states(who.tenant_id, accounts)
    tokens = await apps.connections.store.team_tokens(who.tenant_id, [str(a["id"]) for a in accounts])
    listed: list[dict[str, Any]] = []
    for a in accounts:
        state, status, why = states[str(a["id"])]
        at = (tokens.get(str(a["id"])) or {}).get("refreshed_at")
        listed.append(
            {
                "id": str(a["id"]),
                "name": str(a.get("account_name") or a["name"]),
                "sandbox": bool(a.get("sandbox")),
                "state": state,
                "status": status,
                "stateReason": why,
                "signIn": a.get("sign_in") or "team",
                "connectedAt": at.isoformat() if at else None,
            }
        )
    kinds = apps.connections.kinds()
    return {
        **await _row(apps, who, cred, card, accounts),
        "accountsList": listed,
        "redirectUri": kinds.get("redirectUri"),
        "updated": cred["updated_at"].isoformat() if cred else None,
    }


async def app_page(apps: Apps, who: Caller, app_id: str) -> dict[str, Any]:
    """An app's page as one answer: a card of the caller's team only, so another team's app is not found."""
    card = await apps.card(who, app_id)
    detail = await apps.connections.detail(who, str(card["connectionId"])) if card.get("connectionId") else None
    mine = own_key(who)
    signed = [p for p in (detail or {}).get("people", []) if p["personId"] == mine]
    people = (
        {str(p["person_id"]) for p in await apps.connections.store.people(who.tenant_id, str(card["connectionId"]))}
        if card.get("connectionId")
        else set[str]()
    )
    tools: list[dict[str, Any]] = []
    usage: list[dict[str, Any]] = []
    app = next((a for a in BUILT_IN if f"builtin:{a['id']}" == card["id"]), None)
    for module_id in card["moduleIds"]:
        module = await apps.modules.get(who.tenant_id, module_id)
        if module is None:
            continue
        mine_ops = set(_built_in(app, module)) if app else None
        for op in cast(list[dict[str, Any]], module.get("operations") or []):
            name = str(op["name"])
            if mine_ops is not None and name not in mine_ops:
                continue
            title = tool_title(module, name, apps.plugins.title_of if apps.plugins else None)
            tools.append({"name": name, "title": title or name, "access": str(op["access"])})
    if apps.users is not None and tools:
        try:
            uses = await apps.users.of(who.tenant_id, who.team.id, [t["name"] for t in tools])
        except ServiceUnavailable:
            # The page still answers; each tool's Used by then reads as not known, never as nobody.
            uses = None
        if uses is not None:
            for t in tools:
                found = uses.get(t["name"], [])
                t["usedBy"] = {
                    k: [{"id": u["id"], "name": u["name"]} for u in found if u["kind"] == kind]
                    for k, kind in (("agents", "agent"), ("workflows", "workflow"))
                }
    if apps.calls is not None and card["moduleIds"]:
        ran = await apps.calls.executions(
            who, page=1, page_size=20, tool=None, module_ids=list(card["moduleIds"]), thread_id=None, decision=None
        )
        usage = list(ran["data"])
    skills: list[dict[str, Any]] = []
    plugin = _plugin(apps, card)
    if plugin is not None:
        skills = [{"kind": t.kind, "id": t.id, "title": view_of(plugin, t)["title"]} for t in plugin.manifest.templates]
    accounts = await _accounts(apps, who, card)
    return {
        "card": card,
        "connection": detail,
        "me": {"connected": bool(signed), "account": signed[0].get("account") if signed else None},
        "peopleCount": len(people),
        "accounts": accounts,
        "people": await _people(apps, who, accounts),
        "tools": tools,
        "skills": skills,
        "usage": usage,
    }


async def _people(apps: Apps, who: Caller, accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each person's own sign-in on the app's accounts, joined to the account it is on, with its state and whether it
    is the person's default among several."""
    names = {str(a["id"]): str(a["name"]) for a in accounts}
    mine = own_key(who)
    everyone = apps.connections.may_manage(who)
    now = apps.connections.clock()
    out: list[dict[str, Any]] = []
    sandboxes = {str(a["id"]) for a in accounts if a.get("sandbox")}
    rows = [
        t
        for t in await apps.connections.store.sign_ins(who.tenant_id, list(names))
        if everyone or t["person_id"] == mine
    ]
    defaults: dict[str, str | None] = {}
    for person in {str(t["person_id"]) for t in rows}:
        # Newest first and then by account, the order the call-time pick reads them in (`own_sign_ins`).
        own = sorted(
            (t for t in rows if t["person_id"] == person and str(t["connection_id"]) not in sandboxes),
            key=lambda t: str(t["connection_id"]),
        )
        own.sort(key=lambda t: t["refreshed_at"], reverse=True)
        live = [t for t in own if t.get("refused_at") is None]
        pick = default_sign_in(own) if len(live) > 1 else None
        defaults[person] = str(pick["connection_id"]) if pick is not None else None
    for t in rows:
        test = cast(dict[str, Any], t.get("test") or {})
        at = t.get("refreshed_at")
        out.append(
            {
                "personId": str(t["person_id"]),
                "mine": t["person_id"] == mine,
                "account": t.get("account"),
                "accountId": str(t["connection_id"]),
                "accountName": names[str(t["connection_id"])],
                "since": at.isoformat() if at else None,
                "state": person_state(t, now),
                "testFailed": str(test.get("message") or "no reason given") if test.get("status") == "failed" else None,
                "default": None
                if defaults[str(t["person_id"])] is None or str(t["connection_id"]) in sandboxes
                else defaults[str(t["person_id"])] == str(t["connection_id"]),
            }
        )
    return out


async def _accounts(apps: Apps, who: Caller, card: dict[str, Any]) -> list[dict[str, Any]]:
    """The app's accounts for the page, the default (the binding's, or a custom app's first) first."""
    if card["kind"] not in ("plugin", "connection") or not card.get("connectionId"):
        return []
    default = str(card["connectionId"])
    store = apps.connections.store
    found = await store.accounts(who.tenant_id, who.team.id, str(card["id"]))
    stored = sorted(found, key=lambda a: str(a["id"]) != default)
    states = await apps.states(who.tenant_id, stored)
    team_tokens = await store.team_tokens(who.tenant_id, [str(a["id"]) for a in stored])
    mine = own_key(who)
    ids = [str(a["id"]) for a in stored]
    signed = {str(t["connection_id"]): t for t in await store.own_sign_ins(who.tenant_id, mine, ids)}
    out: list[dict[str, Any]] = []
    for a in stored:
        state = states[str(a["id"])]
        per_person = (a.get("sign_in") or "team") != "team"
        own = signed.get(str(a["id"])) if per_person else None
        out.append(
            {
                "id": str(a["id"]),
                "name": a.get("account_name") or a["name"],
                "default": str(a["id"]) == default,
                "sandbox": bool(a.get("sandbox")),
                "state": state[0],
                "status": state[1],
                "statusDetail": a.get("status_detail"),
                "stateReason": state[2],
                "mine": str(a["id"]) in signed,
                "account": (signed.get(str(a["id"])) or {}).get("account"),
                # On an account each person signs in to, the caller's own sign-in's test; else the team account's.
                "test": own.get("test") if own is not None else team_test(a, team_tokens.get(str(a["id"]))),
                "health": a.get("health"),
            }
        )
    return out


def apps_router(apps: Apps, directory: Directory) -> APIRouter:
    caller = caller_in(directory)
    r = APIRouter(tags=["apps"], responses=ERRORS)

    @r.get("/v1/apps", response_model=Envelope[list[SystemCard]])
    async def list_apps(  # pyright: ignore[reportUnusedFunction]
        who: Annotated[Caller, Depends(caller)],
        acting: ActingPerson,
        include: Annotated[Literal["builtin"] | None, Query()] = None,
    ) -> JSONResponse:
        """The team's apps for the Apps grid: its plugins and the apps a person added. `include=builtin` adds
        the built-in apps, for the approval policy's app picker. A service asking for a person (X-Acting-For) reads
        each card's state as that person's."""
        person = acting.sub if acting else None
        cards = await apps.cards(who, listed=True, builtins=include == "builtin", person=person)
        return ok([SystemCard(**c).model_dump(by_alias=True) for c in cards])

    @r.post("/v1/apps", response_model=Envelope[AccountDetail], status_code=201)
    async def add_app(body: NewAppIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """A custom app, as its first account, which the answer is (its id is the app's): by name with a sign-in kind,
        or an MCP server by its address, whose sign-in is found from the server."""
        return ok(await apps.add_custom(who, body), 201)

    @r.get("/v1/app-credentials", response_model=Envelope[list[AppCredential]])
    async def list_app_credentials(  # pyright: ignore[reportUnusedFunction]
        who: Annotated[Caller, Depends(caller)], app: Annotated[str | None, Query(max_length=200)] = None
    ) -> JSONResponse:
        """The team's app credentials and Ops AI's app of each app using it, for the Credentials page and the pickers
        that name one (`app` keeps one app's): type, client id, permissions, accounts on it and the last Test with my
        account. Team admins only; no secret."""
        return ok([AppCredential(**c).model_dump(by_alias=True) for c in await app_credentials(apps, who, app)])

    @r.post("/v1/app-credentials", response_model=Envelope[AppCredentialDetail], status_code=201)
    async def create_app_credential(  # pyright: ignore[reportUnusedFunction]
        body: AppCredentialIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Adds the team's own OAuth app for one of its apps: name, client id, secret and permissions, with no account
        needed; an account picks it by credentialId when connected. Team admins only; the answer has no secret."""
        return ok(AppCredentialDetail(**await add_app_credential(apps, who, body)).model_dump(by_alias=True), 201)

    @r.get("/v1/app-credentials/{credential_id}", response_model=Envelope[AppCredentialDetail])
    async def get_app_credential(credential_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """One app credential's page: its app, client id, permissions, who made it and the accounts signing in with it,
        each with its state. `ops-ai:<app>` is Ops AI's app of one app. Team admins only; no secret."""
        return ok(AppCredentialDetail(**await app_credential(apps, who, credential_id)).model_dump(by_alias=True))

    @r.put("/v1/app-credentials/{credential_id}/secret", response_model=Envelope[AppCredentialDetail])
    async def set_app_credential_secret(  # pyright: ignore[reportUnusedFunction]
        credential_id: str, body: CredentialSecretIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Replaces the client secret of the team's own app credential. Team admins only; the answer has no secret."""
        row = await replace_credential_secret(apps, who, credential_id, body.client_secret)
        return ok(AppCredentialDetail(**row).model_dump(by_alias=True))

    @r.get("/v1/apps/{app_id}", response_model=Envelope[AppPage])
    async def get_app(app_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """One app's page: its card, accounts, the caller's own sign-in, tools, skills and latest runs."""
        return ok(AppPage(**await app_page(apps, who, app_id)).model_dump(by_alias=True))

    @r.put("/v1/apps/{app_id}/team", response_model=Envelope[SystemCard])
    async def set_team_app(  # pyright: ignore[reportUnusedFunction]
        app_id: str, body: TeamPluginIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Turns a plugin's app on or off for the team and saves the team's settings: a team admin's alone. The first
        turn-on makes the team's default account."""
        if apps.plugin_accounts is None:
            raise NotFound(f"App {app_id}")
        await apps.plugin_accounts.switch(who, app_id, body)
        return ok(SystemCard(**await apps.card(who, app_id)).model_dump(by_alias=True))

    @r.post("/v1/apps/{app_id}/accounts", response_model=Envelope[AccountDetail], status_code=201)
    async def add_account(  # pyright: ignore[reportUnusedFunction]
        app_id: str, body: AccountIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Another account of one of the team's apps: a sandbox, which test runs use, or another named account
        (a second org of the same system). The first stays the default."""
        return ok(await apps.add_account(who, app_id, body), 201)

    return r
