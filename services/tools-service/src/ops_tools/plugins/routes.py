"""A plugin's app for a team: its turn-on and accounts (`PluginAccounts`, which the Apps routes call), and the
routes only a plugin's app has: who uses it, its update, and the knowledge sources it offers.

A team admin (connections.manage in the team) turns a plugin on or off for the team and gives its settings and the
OAuth app the team signs in with; the first turn-on makes the team's default account from the plugin's connection
definition. An installed plugin is available to every team; turning it off keeps its accounts, settings and sign-ins,
so turning it on again needs nothing more."""

# No `from __future__ import annotations`: FastAPI resolves the `Depends(caller)` annotations at import.

from typing import Annotated, Any, Literal, Protocol, cast
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_plugin_sdk import Plugin
from ops_plugin_sdk.knowledge import source_hosts
from ops_plugin_sdk.manifest import Setting
from ops_plugin_sdk.versions import declarations, diff, digest, tools_of
from ops_service_kit.errors import Conflict, NotFound, ServiceUnavailable, Unprocessable, ValidationFailed
from ops_service_kit.http import Envelope, ok

from ..auth.kinds import Kind, kind_of
from ..callers import caller_in
from ..connections.schemas import CREDENTIAL_MAX, AccountIn
from ..connections.service import ConnectionService, connection_rights
from ..held_hosts import HostHeld
from ..modules.directory import Directory
from ..modules.routes import ERRORS
from ..modules.service import Caller
from ..modules.tool_users import ToolUsers
from ..store.connections import DEFAULT_VALUE, PLUGIN_APP, AccountNameTaken, plugin_of, split_config
from .host import (
    PluginHost,
    filled_at_sign_in,
    first_tools_on,
    fixed_fields,
    offered,
    per_account,
    readable,
    render,
    sign_in_fixed,
)

# The OAuth app's own fields: an app credential's, made under Credentials, never typed into an account.
CLIENT_FIELDS = ("clientId", "clientSecret")


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class TeamPluginIn(_Wire):
    enabled: bool
    settings: dict[str, Any] = Field(default_factory=dict[str, Any])
    # The team's app credential (GET /v1/app-credentials) the account signs in with; left out of the first turn-on,
    # Ops AI's app, and of a later one, the account keeps the app it has. Null puts it on Ops AI's app.
    credential_id: str | None = Field(default=None, min_length=1, max_length=64)
    sign_in: str | None = None
    # Which of the plugin's sign-in kinds the team's account uses, the first it lists when left out. It is
    # chosen at the first turn-on only: an account's kind never changes.
    kind: str | None = Field(default=None, max_length=50)
    # The kind's own fields and the client certificate's (auth/kinds.py), secret parts included: an API key, a username
    # and password, a token, a certificate and its private key. A secret part is sealed and never answered back; one
    # left out of a later turn-on keeps its value.
    credentials: dict[str, Annotated[str, Field(max_length=CREDENTIAL_MAX)]] = Field(
        default_factory=dict[str, str], max_length=20
    )
    # The team account's name, from the Connect window; taken at the first turn-on, the app's title when left
    # out. A later rename goes through the account's PATCH.
    account_name: str | None = Field(default=None, min_length=1, max_length=200)
    # Whether the first account is a sandbox, which only test runs use.
    sandbox: bool = False


class InputChanges(_Wire):
    added: list[str]
    removed: list[str]
    changed: list[str]


class ToolChange(_Wire):
    """One tool an update adds, changes or removes, by its operation name."""

    name: str
    title: str
    access: str
    change: Literal["new", "changed", "removed"]
    inputs: InputChanges
    # The other fields of its manifest entry that changed: request, headers, access, requires_approval, amount_max...
    changed: list[str]
    # A Python tool runs the installed package's function whatever version the team runs.
    python: bool


class VersionRef(_Wire):
    version: str
    digest: str


class PluginUpdateView(_Wire):
    """What taking the installed version would change for the team: empty `tools` when it runs it already."""

    version: str | None
    digest: str | None
    installed: VersionRef
    available: bool
    headers_changed: bool
    tools: list[ToolChange]


class AppUser(_Wire):
    id: str
    name: str
    # The app's tools this agent or workflow uses, by operation name.
    tools: list[str]


class AppUsers(_Wire):
    """Who uses an app's tools in the team, read before turning it off."""

    agents: list[AppUser]
    workflows: list[AppUser]


class TakeUpdateIn(_Wire):
    # The installed version's digest the review was read at; another upgrade since then refuses the take.
    digest: str = Field(min_length=64, max_length=64)


class SourceHostsIn(_Wire):
    plugin: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=200)
    # The source's own values (its start addresses): the hosts asked about are the ones its egress_from input holds.
    values: dict[str, Any] = Field(default_factory=dict[str, Any])


class SourceHost(_Wire):
    host: str
    # allowed: listed, or passing under the account's any_public policy; waiting: an admin has yet to approve it;
    # refused: the Security team refused it, or the account adds no new hosts.
    state: Literal["allowed", "waiting", "refused"]
    # The Security task a waiting host is asked on (Human Tasks), when the account's policy asks Security.
    run_key: str | None = None
    reason: str | None = None


class HostGate(Protocol):
    async def hold_unless_listed(self, who: Caller, host: str | None, app: str) -> None: ...
    async def host_passes(self, tenant_id: str, host: str) -> bool: ...


class KnowledgeSourceView(_Wire):
    plugin: str
    source: str
    title: str
    list_tool: str
    get_tool: str
    deleted_tool: str | None
    # The contract's optional tools: changes since a cursor, and the pickers a person chooses scopes with.
    changes_tool: str | None = None
    scopes_tool: str | None = None
    preview_tool: str | None = None
    # Every listing names every item, so each run finds what left the source.
    lists_whole: bool = False
    fetch_at_once: int = 4
    # Its items are pages of one website.
    site: bool = False
    # What a source of this kind is set up with, checked by kb-service and sent to each tool as `source`; and the
    # input whose addresses the source's sync may reach.
    inputs: dict[str, Any] = Field(default_factory=dict[str, Any])
    egress_from: str | None = None
    # Whether the get tool takes the version tag kb-service holds, to answer `unchanged` without the content.
    get_takes_tag: bool = False
    # A plugin that signs in to nothing (a public website) needs no connection for a source.
    needs_connection: bool = True
    schedule: dict[str, Any]
    connection_id: str | None
    sign_in: str | None
    # healthy, needs_reconnect, error, ...: a source paused for a reconnect resumes once Test connection passes.
    connection_status: str | None


def _split(plugin: Plugin, given: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """A save's settings as the team's and the account's own (the sign-in address): the team's stay on the
    binding, the account's go on the account, kept there once."""
    own = per_account(plugin.manifest)
    return {k: v for k, v in given.items() if k not in own}, {k: v for k, v in given.items() if k in own}


def not_offered(title: str, setting: Setting, value: Any) -> str:
    """The plain refusal of a value outside a setting's choices: what was given, and what may be."""
    places = [c.label for c in setting.choices or []]
    other = setting.other
    if other is not None:
        places.append(f"{other.label.lower()} ending in {' or '.join(other.hosts)}")
    said = places[0] if len(places) == 1 else f"{', '.join(places[:-1])} or {places[-1]}"
    return f"{title} cannot use {value} there. Choose {said}."


class PluginAccounts:
    """A plugin's app for one team: turning it on, its accounts, and the sign-in settings each account takes from the
    plugin's connection definition."""

    def __init__(self, host: PluginHost, connections: ConnectionService) -> None:
        self.host = host
        self.connections = connections

    def plugin(self, app_id: str) -> Plugin:
        """The plugin an app id (`plugin:<id>`) names; NotFound for any other app."""
        plugin = self.host.plugins.get(app_id.removeprefix(PLUGIN_APP)) if app_id.startswith(PLUGIN_APP) else None
        if plugin is None:
            raise NotFound(f"App {app_id}")
        return plugin

    def _ops_client_id(self, plugin_id: str) -> str | None:
        """The client id of Ops AI's own app for the plugin, from the install config; None when the install set none."""
        found = self.connections.store.install_client(plugin_id)
        return found.id if found else None

    def manages(self, who: Caller) -> None:
        """Refuses a caller who may not manage the team's plugins."""
        if who.principal is not None:
            connection_rights(who.principal, "manage", what="the team's apps")

    def _team_settings(self, plugin: Plugin, held: dict[str, Any], given: dict[str, Any]) -> dict[str, Any]:
        """The binding's settings after a save: the team's only; an account's own are the account's, so a copy
        left from before (a removed account's instance) never reaches a call."""
        mine = per_account(plugin.manifest)
        return {k: v for k, v in held.items() if k != "environments" and k not in mine} | given

    def _checked_settings(self, plugin: Plugin, given: dict[str, Any]) -> None:
        m = plugin.manifest
        locked = self.host.locked_settings(m.id)
        for k, value in given.items():
            setting = m.settings.get(k)
            if setting is None:
                raise ValidationFailed(f"{k} is not a setting of {m.title}.", details={"field": k})
            if k in locked:
                raise ValidationFailed(f"{k} is set by the platform admin for every team.", code="setting_locked")
            if setting.at_sign_in:
                raise ValidationFailed(f"{k} is read from the sign-in, not typed.", code="setting_from_token")
            # An empty value unsets it, so the plugin's default (one of its choices) applies.
            if value not in (None, "") and not offered(setting, value):
                raise ValidationFailed(
                    not_offered(m.title, setting, value), code="setting_not_offered", details={"field": k}
                )

    async def switch(self, who: Caller, app_id: str, body: TeamPluginIn) -> None:
        """Turns the plugin on or off for the team and saves the team's settings: a team admin's alone. The first
        turn-on makes the team's default account; a later one with sign-in details sets them on it."""
        self.manages(who)
        plugin = self.plugin(app_id)
        m = plugin.manifest
        self._checked_settings(plugin, body.settings)
        before = await self.host.bindings.get(who.tenant_id, who.team.id, m.id) or {}
        team, own = _split(plugin, body.settings)
        settings = self._team_settings(plugin, dict(before.get("settings") or {}), team)
        connection_id = before.get("connection_id")
        store = self.connections.store
        if connection_id is not None and await store.get(who.tenant_id, str(connection_id)) is None:
            # Removed, as the connect dialog's Cancel removes the one it made: the next turn-on makes another.
            connection_id = None
        package = m.connection.runs_on is not None
        if package and body.enabled and m.connection.runs_on not in self.host.plugins:
            raise ValidationFailed(
                f"{m.title} runs inside an app this install does not have; the person who runs Ops AI installs it "
                "first.",
                code="host_app_missing",
            )
        # A pack (templates only, no endpoint) reaches no system, so turning it on makes no account.
        accountless = package or not m.endpoint
        if accountless:
            # A package app has no account of its own: each call signs in with the chosen account of the app it
            # runs on (PluginHost.for_call).
            connection_id = None
        elif body.enabled and connection_id is None:
            connection_id = await self.connect(
                who, plugin, settings, own, body, account_name=body.account_name, sandbox=body.sandbox
            )
        elif body.enabled and ("credential_id" in body.model_fields_set or body.credentials or body.kind or own):
            await self.keys(who, plugin, str(connection_id), settings, body, own=own)
        await self.host.bindings.put(
            who.tenant_id,
            who.team.id,
            m.id,
            enabled=body.enabled,
            connection_id=connection_id,
            settings=settings,
            by=who.name,
        )
        if not before or (body.enabled and not before.get("connection_id") and before.get("tools_on") is None):
            # A first turn-on, including one over a binding made before the team ever had an account (start_binding,
            # the plugin catalog), starts with the app's read tools added and the installed version taken.
            await self._first_binding(who, plugin)
        elif self.host.versions and not before.get("version"):
            await self.host.take_installed(who.tenant_id, who.team.id, plugin)
        if body.enabled and not accountless and not before.get("connection_id") and body.credential_id is None:
            await self._fix_first_place(who, plugin, own)

    async def _fix_first_place(self, who: Caller, plugin: Plugin, own: dict[str, Any]) -> None:
        """The first turn-on on Ops AI's app: where it signs in (the plugin's `asked: config` values the window asked)
        is kept on Ops AI's auth config for the team as a default, so the next account's window offers it and a second
        org can sign in at its own address. A value the team already set on that config, and its mode, are kept: a team
        that turned the app on while the first value was fixed stays fixed."""
        m = plugin.manifest
        given = {k: v for k, v in own.items() if k in m.config_settings and v not in (None, "")}
        b = await self.host.bindings.get(who.tenant_id, who.team.id, m.id) or {}
        held = {k: v for k, v in dict(b.get("config_settings") or {}).items() if v not in (None, "")}
        fresh = {k: v for k, v in given.items() if k not in held}
        if not fresh:
            return
        modes = {**dict(b.get("setting_modes") or {}), **dict.fromkeys(fresh, DEFAULT_VALUE)}
        await self.host.bindings.set_config(who.tenant_id, who.team.id, m.id, {**held, **fresh}, modes, by=who.name)

    async def make_team_default(self, who: Caller, app_id: str, account_id: str) -> None:
        """Makes one of the team's live accounts of a plugin's app the one calls naming no account use: a team admin's
        alone. A sandbox only test runs use, so it is refused."""
        self.manages(who)
        m = self.plugin(app_id).manifest
        before = await self.host.bindings.get(who.tenant_id, who.team.id, m.id)
        account = await self.connections.store.get(who.tenant_id, account_id)
        if before is None or account is None or account["app_id"] != app_id or account["team_id"] != who.team.id:
            raise NotFound(f"Account {account_id}")
        if account.get("sandbox"):
            raise ValidationFailed(
                "A sandbox account is used by test runs only, so it cannot be the default.", code="sandbox_default"
            )
        await self.host.bindings.put(
            who.tenant_id,
            who.team.id,
            m.id,
            enabled=bool(before.get("enabled")),
            connection_id=account_id,
            settings=dict(before.get("settings") or {}),
            by=who.name,
        )

    async def add_account(self, who: Caller, app_id: str, body: AccountIn) -> str:
        """Another account of a plugin's app, a test account or another live one (a second org of the same system), made
        with the first's contract; the first stays the default. With no account yet, it is the app's first and default,
        and the app is turned on for the team."""
        self.manages(who)
        plugin = self.plugin(app_id)
        m = plugin.manifest
        b = await self.host.bindings.get(who.tenant_id, who.team.id, m.id)
        name = body.name.strip()
        if not name:
            raise ValidationFailed("Name the account.", details={"field": "name"})
        if await self.host.account_named(who.tenant_id, who.team.id, plugin, name) is not None:
            raise AccountNameTaken(name)
        first = b.get("connection_id") if b else None
        if first is None or await self.connections.store.get(who.tenant_id, str(first)) is None:
            # The team has no account of the app yet: this one is its first, made as turning the app on makes it.
            await self.switch(
                who,
                app_id,
                TeamPluginIn(
                    enabled=True,
                    settings=dict(body.settings),
                    credential_id=body.credential_id,
                    sign_in=body.sign_in,
                    kind=body.kind,
                    credentials=dict(body.credentials),
                    account_name=name,
                    sandbox=body.sandbox,
                ),
            )
            made = await self.host.bindings.get(who.tenant_id, who.team.id, m.id)
            return str((made or {})["connection_id"])
        assert b is not None
        self._checked_settings(plugin, body.settings)
        team, own = _split(plugin, body.settings)
        if team:
            raise ValidationFailed(
                f"{', '.join(sorted(team))} is the team's setting of {m.title}, not one account's.",
                code="setting_not_per_account",
            )
        settings = self._team_settings(plugin, dict(b.get("settings") or {}), {})
        if not body.sandbox:
            # Another live account signs in where the first does unless it names its own address; a sandbox, which
            # signs in elsewhere, names its own.
            first = await self.connections.store.get(who.tenant_id, str(b["connection_id"])) or {}
            c = m.connection
            # What the sign-in itself fills (an org's instance) is the first account's own, so it is never copied.
            filled = set(c.from_token) | ({c.after_sign_in.setting} if c.after_sign_in else set[str]())
            held = dict(first.get("plugin_settings") or {})
            own = {**{k: v for k, v in held.items() if k in per_account(m) and k not in filled}, **own}
        # Whose account its calls use is the first account's unless the add says otherwise, so a second org of a
        # team that signs in as the team is not one each person must connect.
        held_first = await self.connections.store.get(who.tenant_id, str(b["connection_id"])) or {}
        given = TeamPluginIn(
            enabled=True,
            credential_id=body.credential_id,
            sign_in=body.sign_in or held_first.get("sign_in"),
            kind=body.kind,
            credentials=dict(body.credentials),
        )
        made = await self.connect(who, plugin, settings, own, given, account_name=name, sandbox=body.sandbox)
        if body.make_default and not body.sandbox:
            await self.make_team_default(who, app_id, made)
        return made

    def _kind(self, plugin: Plugin, body: TeamPluginIn) -> Kind:
        """The sign-in kind the team chose, one the plugin offers; the first it lists when none is named."""
        offered = plugin.manifest.connection.kinds
        chosen = body.kind or offered[0]
        if chosen not in offered:
            raise ValidationFailed(
                f"{plugin.manifest.title} signs in with {', '.join(offered)}.",
                code="kind_not_offered",
                details={"field": "kind"},
            )
        return kind_of(chosen)

    def _credentials(self, plugin: Plugin, kind: Kind, given: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        """The credentials split into plain settings and secret parts, each a field of the kind or of the client
        certificate; any other name is refused rather than dropped, so a typo never leaves an account unsigned. A
        field the plugin sets itself (its addresses, its permissions) is refused too: it would replace the plugin's."""
        plain: dict[str, str] = {}
        secret: dict[str, str] = {}
        fixed = {"baseUrl", "testPath", *fixed_fields(plugin.manifest)}
        for k, v in given.items():
            f = kind.field(k)
            if k in CLIENT_FIELDS and f is not None:
                raise ValidationFailed(
                    f"{f.label} is the OAuth app's: add it under Credentials and name it as credentialId.",
                    code="client_in_credentials",
                    details={"field": f"credentials.{k}"},
                )
            if f is not None and k in fixed:
                raise ValidationFailed(
                    f"{k} is set by {plugin.manifest.title} itself, not typed.",
                    code="setting_fixed",
                    details={"field": f"credentials.{k}"},
                )
            if f is None:
                raise ValidationFailed(
                    f"{k} is not part of signing in with {kind.label}.", details={"field": f"credentials.{k}"}
                )
            (secret if f.secret else plain)[k] = v
        return plain, secret

    async def connect(
        self,
        who: Caller,
        plugin: Plugin,
        settings: dict[str, Any],
        own: dict[str, Any],
        body: TeamPluginIn,
        *,
        account_name: str | None = None,
        sandbox: bool = False,
    ) -> str:
        """An account of the plugin's app, from the plugin's definition, made whole in one call for every kind:
        its address, its test path, how its key is sent, the credentials the team gave, and for a kind that holds a
        token the OAuth app and its addresses. An instance the token names comes later, at sign-in."""
        m = plugin.manifest
        c = m.connection
        kind = self._kind(plugin, body)
        # Personal sign-in is on by default where the plugin offers it with the team as backup: people may add their
        # own account, and calls for those who have not use the team's sign-in.
        backed = "person_or_team" in c.sign_in and kind.per_person
        sign_in = body.sign_in or ("person_or_team" if backed else c.sign_in[0])
        if sign_in not in c.sign_in:
            raise ValidationFailed(f"{m.title} signs in with {', '.join(c.sign_in)}.", code="sign_in_not_offered")
        plain, secret = self._credentials(plugin, kind, body.credentials)
        # A token kind's client secret comes from the team's own app or the platform's, checked when it is used.
        # On an account each person signs in to, their own key, password or token is theirs to give.
        each_person = sign_in == "person" and kind.per_person
        missing = [
            f.label
            # The plugin's own clientAuth counts, so one that signs an assertion asks for the signing pair.
            for f in kind.requires({**plain, **sign_in_fixed(plugin.manifest)}, each_person=each_person)
            if f.secret and f.name not in secret and not (kind.holds_token and f.name == "clientSecret")
        ]
        if kind.holds_token and not body.credential_id and self._ops_client_id(m.id) is None:
            raise ValidationFailed(
                f"Give the OAuth app's client id to turn {m.title} on; this install has no app of its own for it.",
                code="client_missing",
            )
        if missing:
            raise ValidationFailed(f"{m.title} needs {', '.join(missing)} to sign in with {kind.label}.")
        # The same create contract as a custom app's account (cross-card review): the row carries the system's
        # card details from the manifest, so a plugin's account and one made by hand hold the same columns.
        shown = m.display
        made = await self.connections.create(
            who,
            {
                "name": account_name or m.title,
                # The app's account: the plugin it belongs to, and its name, the app's title for the first.
                "plugin_id": m.id,
                "account_name": account_name or m.title,
                "sandbox": sandbox,
                "auth_kind": kind.id,
                "sign_in": sign_in if kind.per_person else "team",
                "category": shown.category,
                "description": shown.description,
                "docs_url": shown.docs_url,
            },
        )
        try:
            await self.keys(who, plugin, str(made["id"]), settings, body, own=own)
        except ValidationFailed:
            # An account the team cannot use is not left behind for the next turn-on to trip over.
            await self.connections.delete(who, str(made["id"]))
            raise
        return str(made["id"])

    async def keys(
        self,
        who: Caller,
        plugin: Plugin,
        connection_id: str,
        settings: dict[str, Any],
        body: TeamPluginIn,
        *,
        own: dict[str, Any],
    ) -> None:
        """The plugin's account's sign-in settings: the system's address (the endpoint's origin, or the sign-in host's
        until the token names the instance), the health check as Test connection's path, how an API key is sent, the
        team's credentials over what the account already holds, and for a kind that holds a token the OAuth app (the
        team's own first, else the platform's, set up once by an account admin) and its addresses, rendered with
        the account's settings."""
        conn = await self.connections.store.get(who.tenant_id, connection_id)
        keys, secret, client, platform_id, mine = await self._rendered(who, plugin, conn, settings, body, own=own)
        if platform_id is not None:
            await self.connections.use_platform_app(who, connection_id, plugin.manifest.id, keys, plugin_settings=mine)
            return
        await self.connections.change(
            who,
            connection_id,
            {"revision": int(conn["revision"]) if conn else 1, "settings": keys, "secret_values": secret, **client},
            plugin_settings=mine,
        )

    async def own_place(
        self, who: Caller, src: dict[str, Any], given: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """A person's second account of their own on the app of account `src`, signing in where `given` says (the
        app's per-account settings, such as a company server's address): its sign-in settings and its own plugin
        settings, rendered as the team's turn-on renders an account's, with the same auth config as `src`. What
        `src`'s sign-in filled (its org's instance) is never carried over. Raises for a setting that is the team's
        or a value the plugin does not offer."""
        pid = plugin_of(src)
        plugin = self.host.plugins.get(pid) if pid else None
        if plugin is None:
            raise ValidationFailed(f"{src['name']} is not a plugin's account, so it keeps its own address.")
        m = plugin.manifest
        self._checked_settings(plugin, given)
        team, own = _split(plugin, given)
        if team:
            raise ValidationFailed(
                f"{', '.join(sorted(team))} is the team's setting of {m.title}, not one account's.",
                code="setting_not_per_account",
            )
        b = await self.host.bindings.get(who.tenant_id, who.team.id, m.id) or {}
        settings = self._team_settings(plugin, dict(b.get("settings") or {}), {})
        held = {k: v for k, v in dict(src.get("plugin_settings") or {}).items() if k in per_account(m)}
        start = {**src, "plugin_settings": {k: v for k, v in held.items() if k not in filled_at_sign_in(m)}}
        keys, _, _, _, mine = await self._rendered(who, plugin, start, settings, TeamPluginIn(enabled=True), own=own)
        return keys, mine

    async def _rendered(
        self,
        who: Caller,
        plugin: Plugin,
        conn: dict[str, Any] | None,
        settings: dict[str, Any],
        body: TeamPluginIn,
        *,
        own: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, str], dict[str, Any], str | None, dict[str, Any]]:
        """What `keys` writes on account `conn` (None for one not made yet): its sign-in settings, its secret parts,
        its own app credential when it changes, Ops AI's app's client id when it signs in with that, and its own plugin
        settings."""
        m = plugin.manifest
        c = m.connection
        kind = kind_of(str(conn["auth_kind"])) if conn else self._kind(plugin, body)
        if body.kind and body.kind != kind.id:
            raise ValidationFailed(
                f"{m.title}'s account signs in with {kind.label}; its kind is chosen once, when it is made.",
                code="kind_fixed",
                details={"field": "kind"},
            )
        plain, secret = self._credentials(plugin, kind, body.credentials)
        held = (conn or {}).get("credential_id") if not (conn or {}).get("platform_app") else None
        chosen = body.credential_id if "credential_id" in body.model_fields_set else held
        cred = await self.connections.store.credential(who.tenant_id, chosen) if chosen and kind.holds_token else None
        # The account's own settings, those given over those it holds, over the auth config's defaults. A fixed value
        # of the config is every account's: a team credential's is read from it and never copied onto the account;
        # the team's on Ops AI's app (the install's client, with nowhere else to read it from) is written onto each.
        fixed, defaults = await self.config_values(who, plugin, cred)
        mine = {**defaults, **dict((conn or {}).get("plugin_settings") or {}), **own}
        if cred is not None:
            mine = {k: v for k, v in mine.items() if k not in fixed}
        else:
            mine |= fixed
        merged = self.host.settings(plugin, settings, {**mine, **fixed})
        before = cast(dict[str, Any], (conn or {}).get("settings") or {})
        keys: dict[str, Any] = dict(before)
        endpoint = render(m.endpoint, merged)
        platform_id: str | None = None
        client: dict[str, Any] = {}
        # The OAuth client is the account's credential (credential_id) or Ops AI's app (platform_app), never a setting.
        keys.pop("clientId", None)
        if kind.holds_token:
            # A later turn-on that names no credential keeps the one the account has (`held`); else Ops AI's app.
            if chosen and (cred is None or cred["team_id"] != who.team.id or cred["app_id"] != f"{PLUGIN_APP}{m.id}"):
                raise ValidationFailed(
                    f"Pick one of the team's app credentials for {m.title}.",
                    code="credential_not_found",
                    details={"field": "credentialId"},
                )
            if cred is None:
                platform_id = self._ops_client_id(m.id)
                if platform_id is None:
                    raise ValidationFailed(
                        f"Add an app credential for {m.title} under Credentials and pick it; this install has no app "
                        "of its own for it.",
                        code="client_missing",
                    )
            elif chosen != held:
                client = {"credential_id": chosen}
            scopes = str((cred or {}).get("scopes") or "") or " ".join(s.id for s in c.scopes)
            keys |= {"scopes": scopes}
            for key, template in (
                ("authorizeUrl", c.authorize_url),
                ("tokenUrl", c.token_url),
                ("revokeUrl", c.revoke_url),
            ):
                if template and kind.field(key) is not None:
                    value = render(template, merged)
                    if value is None:
                        raise ValidationFailed(f"Set {m.title}'s settings its sign-in addresses need first.")
                    keys[key] = value
            if c.client_auth and kind.field("clientAuth") is not None:
                keys["clientAuth"] = c.client_auth
            if c.authorize_params and kind.field("authorizeParams") is not None:
                params = {k: render(v, merged) for k, v in c.authorize_params.items()}
                if any(v is None for v in params.values()):
                    raise ValidationFailed(f"Set {m.title}'s settings its sign-in parameters need first.")
                keys["authorizeParams"] = urlencode(params)
        # Credentials go to the system's address only: the endpoint's origin, or before the token names the instance,
        # the sign-in host's, which the sign-in replaces (host.on_token).
        base = endpoint or render(c.authorize_url or "", merged)
        if not base:
            raise ValidationFailed(f"Set {m.title}'s settings its address needs first.")
        parts = urlsplit(base)
        keys["baseUrl"] = f"{parts.scheme}://{parts.netloc}"
        check = c.health_check
        path = render(check.path, merged) if check and endpoint else None
        if path:
            keys["testPath"] = path
        if kind.id == "api_key" and c.api_key is not None:
            keys |= {"placement": c.api_key.placement, "name": c.api_key.name}
        keys |= plain
        return keys, secret, client, platform_id, mine

    async def config_values(
        self, who: Caller, plugin: Plugin, cred: dict[str, Any] | None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """An auth config's (fixed, default) values: the team's app credential's, or with none the team's on Ops AI's
        app, which its binding of the plugin holds."""
        if cred is not None:
            return split_config(cred.get("settings"), cred.get("setting_modes"))
        b = await self.host.bindings.get(who.tenant_id, who.team.id, plugin.manifest.id) or {}
        return split_config(b.get("config_settings"), b.get("setting_modes"))

    async def start_binding(self, who: Caller, plugin: Plugin) -> dict[str, Any]:
        """The team's binding of the plugin, made off when it has none, as a first turn-on makes it: every tool
        added, and the installed version taken."""
        m = plugin.manifest
        found = await self.host.bindings.get(who.tenant_id, who.team.id, m.id)
        if found is not None:
            return found
        await self.host.bindings.put(
            who.tenant_id, who.team.id, m.id, enabled=False, connection_id=None, settings={}, by=who.name
        )
        await self._first_binding(who, plugin)
        return await self.host.bindings.get(who.tenant_id, who.team.id, m.id) or {}

    async def _first_binding(self, who: Caller, plugin: Plugin) -> None:
        m = plugin.manifest
        # A new app hands agents every tool; its "Ask before changes" switch, not a missing tool, holds a write.
        await self.host.bindings.set_tools(who.tenant_id, who.team.id, m.id, first_tools_on(m))
        if self.host.versions:
            # A team turning a plugin on takes the installed version; a later upgrade waits for its review.
            await self.host.take_installed(who.tenant_id, who.team.id, plugin)

    async def move_to_credential(
        self, who: Caller, plugin: Plugin, connection_id: str, credential_id: str | None
    ) -> None:
        """Puts a plugin account on another of the team's app credentials, or with none on Ops AI's app, its sign-in
        addresses written again from that credential's settings."""
        b = await self.host.bindings.get(who.tenant_id, who.team.id, plugin.manifest.id) or {}
        settings = self._team_settings(plugin, dict(b.get("settings") or {}), {})
        body = TeamPluginIn(enabled=True, credential_id=credential_id)
        await self.keys(who, plugin, connection_id, settings, body, own={})

    async def rewrite_addresses(self, who: Caller, plugin: Plugin, connection_id: str) -> None:
        """Writes a plugin account's sign-in addresses again from its settings as they now are (its app credential's
        changed), keeping its kind, its credential and every setting it holds."""
        b = await self.host.bindings.get(who.tenant_id, who.team.id, plugin.manifest.id) or {}
        settings = self._team_settings(plugin, dict(b.get("settings") or {}), {})
        await self.keys(who, plugin, connection_id, settings, TeamPluginIn(enabled=True), own={})

    def team_values(self, plugin: Plugin, b: dict[str, Any], own: dict[str, Any]) -> dict[str, Any]:
        """The team's settings of the plugin as a person may read them: a secret field never, even as its reference."""
        return readable(plugin.manifest, self.host.settings(plugin, dict(b.get("settings") or {}), own))[0]


def plugins_router(
    accounts: PluginAccounts,
    directory: Directory,
    *,
    users: ToolUsers | None = None,
    hosts: HostGate | None = None,
) -> APIRouter:
    """`users` answers who uses an app's tools (agents-service); without it that route answers 503, never "nobody".
    `hosts` decides a knowledge source's new hosts by the account's egress rule; without it that route answers 503."""
    caller = caller_in(directory)
    host = accounts.host
    r = APIRouter(tags=["apps"], responses=ERRORS)

    def _installed(plugin: Plugin) -> tuple[dict[str, Any], str]:
        decl = declarations(plugin.manifest, plugin.root)
        return decl, digest(decl)

    def _team_tools(plugin: Plugin, b: dict[str, Any]) -> list[str]:
        """The tool names the team's version has, else the installed manifest's."""
        if host.versions and b.get("declarations"):
            return list(tools_of(cast(dict[str, Any], b["declarations"])))
        return [t.name for t in plugin.manifest.tools]

    async def _update(who: Caller, app_id: str) -> tuple[Plugin, dict[str, Any]]:
        """The plugin and the team's binding, for a team admin, with plugin_updates on (404 otherwise)."""
        if not host.versions:
            raise NotFound("Plugin updates are off for this install.")
        accounts.manages(who)
        plugin = accounts.plugin(app_id)
        b = await host.bindings.get(who.tenant_id, who.team.id, plugin.manifest.id)
        if b is None:
            raise NotFound(f"{plugin.manifest.title} is not turned on for this team.")
        return plugin, b

    def _review(plugin: Plugin, b: dict[str, Any]) -> dict[str, Any]:
        m = plugin.manifest
        installed, now = _installed(plugin)
        team = cast(dict[str, Any] | None, b.get("declarations")) or installed
        changes = diff(team, installed)
        tools = [{**t, "name": m.operation(str(t["name"]))} for t in changes["tools"]]
        return PluginUpdateView(
            version=b.get("version"),
            digest=b.get("digest"),
            installed=VersionRef(version=m.version, digest=now),
            available=bool(b.get("digest")) and b.get("digest") != now,
            headers_changed=bool(changes["headers"]),
            tools=[ToolChange.model_validate(t) for t in tools],
        ).model_dump(by_alias=True)

    @r.get("/v1/apps/{app_id}/used-by", response_model=Envelope[AppUsers])
    async def app_users(app_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The team's agents and workflows that use the app's tools, each with the tools it uses: what turning the app
        off stops. A team admin's, as turning it off is."""
        accounts.manages(who)
        plugin = accounts.plugin(app_id)
        if users is None:
            raise ServiceUnavailable("This service cannot ask who uses a tool.", code="tool_users_unavailable")
        b = await host.bindings.get(who.tenant_id, who.team.id, plugin.manifest.id) or {}
        tools = [plugin.manifest.operation(t) for t in _team_tools(plugin, b)]
        found: dict[str, dict[str, dict[str, Any]]] = {"agent": {}, "workflow": {}}
        for tool, uses in (await users.of(who.tenant_id, who.team.id, tools)).items():
            for use in uses:
                row = found[use["kind"]].setdefault(use["id"], {"id": use["id"], "name": use["name"], "tools": []})
                row["tools"].append(tool)
        return ok(
            AppUsers(
                agents=[AppUser(**a) for a in found["agent"].values()],
                workflows=[AppUser(**w) for w in found["workflow"].values()],
            ).model_dump(by_alias=True)
        )

    @r.get("/v1/apps/{app_id}/update", response_model=Envelope[PluginUpdateView])
    async def plugin_update(app_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """What taking the installed plugin version would change for the team: each new, changed and removed tool."""
        plugin, b = await _update(who, app_id)
        return ok(_review(plugin, b))

    @r.post("/v1/apps/{app_id}/update", response_model=Envelope[PluginUpdateView])
    async def take_plugin_update(  # pyright: ignore[reportUnusedFunction]
        app_id: str, body: TakeUpdateIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Takes the installed version for the team, from its next call. The digest is the one the review was read
        at, so a review another upgrade has replaced since is refused rather than taken unseen."""
        plugin, _ = await _update(who, app_id)
        if body.digest != _installed(plugin)[1]:
            raise Conflict(
                f"{plugin.manifest.title} changed again since this review; read the update again.",
                code="update_changed",
            )
        await host.take_installed(who.tenant_id, who.team.id, plugin)
        b = await host.bindings.get(who.tenant_id, who.team.id, plugin.manifest.id) or {}
        return ok(_review(plugin, b))

    @r.post("/v1/knowledge-sources/hosts", response_model=Envelope[list[SourceHost]])
    async def knowledge_source_hosts(body: SourceHostsIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The hosts a source's values would have its sync reach, each decided as any new outside address is: a
        person's request (adding the source) lists it where the account lets them, asks the Security team, or is
        refused under `block`; a service's (kb-service's beat) only reads whether each passes now. A source's hosts
        are never exempt from the account's list."""
        if hosts is None:
            raise ServiceUnavailable("This install decides no egress hosts.")
        plugin = accounts.plugin(f"{PLUGIN_APP}{body.plugin}")
        source = next((s for s in plugin.manifest.knowledge_sources if s.name == body.source), None)
        if source is None:
            raise NotFound(f"{plugin.manifest.title} has no knowledge source {body.source}")
        person = who.principal is not None and who.principal.kind != "service"
        out: list[SourceHost] = []
        for host in source_hosts(source, body.values):
            if not person:
                passes = await hosts.host_passes(who.tenant_id, host)
                out.append(SourceHost(host=host, state="allowed" if passes else "waiting"))
                continue
            try:
                await hosts.hold_unless_listed(who, host, source.title)
            except HostHeld as e:
                out.append(SourceHost(host=host, state="waiting", run_key=e.run_key))
            except (Unprocessable, ValidationFailed) as e:
                out.append(SourceHost(host=host, state="refused", reason=e.message))
            else:
                out.append(SourceHost(host=host, state="allowed"))
        return ok([h.model_dump(by_alias=True) for h in out])

    @r.get("/v1/knowledge-sources", response_model=Envelope[list[KnowledgeSourceView]])
    async def knowledge_sources(who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The knowledge sources a team can create from its plugins that are on, with the account each would read
        through: kb-service lists them and syncs by calling the two tools named here."""
        out: list[dict[str, Any]] = []
        for plugin in host.plugins.values():
            m = plugin.manifest
            if await host.off_reason(who.tenant_id, who.team.id, plugin) is not None:
                continue
            b = await host.bindings.get(who.tenant_id, who.team.id, m.id) or {}
            conn = None
            if b.get("connection_id"):
                conn = await accounts.connections.store.get(who.tenant_id, str(b["connection_id"]))
            for s in m.knowledge_sources:
                out.append(
                    KnowledgeSourceView(
                        plugin=m.id,
                        source=s.name,
                        title=s.title,
                        list_tool=m.operation(s.list),
                        get_tool=m.operation(s.get),
                        deleted_tool=m.operation(s.deleted) if s.deleted else None,
                        changes_tool=m.operation(s.changes) if s.changes else None,
                        scopes_tool=m.operation(s.scopes) if s.scopes else None,
                        preview_tool=m.operation(s.preview) if s.preview else None,
                        lists_whole=s.lists_whole,
                        fetch_at_once=s.fetch_at_once,
                        site=s.site,
                        inputs={k: f.model_dump(exclude_none=True) for k, f in s.inputs.items()},
                        egress_from=s.egress_from,
                        get_takes_tag=(getter := m.tool(s.get)) is not None and "tag" in getter.input,
                        needs_connection=m.connection.kinds != ["none"],
                        schedule=s.schedule.model_dump(),
                        connection_id=b.get("connection_id"),
                        sign_in=(conn or {}).get("sign_in"),
                        connection_status=(conn or {}).get("status"),
                    ).model_dump(by_alias=True)
                )
        return ok(out)

    return r
