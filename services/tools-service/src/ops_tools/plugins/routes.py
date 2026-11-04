"""`/v1/plugins` and `/v1/knowledge-sources`: what a team sees of the installed plugins and turns on.

A team admin (connections.manage in the team) turns a plugin on or off for the team, gives its settings and the OAuth
app the team signs in with; the first turn-on makes the team's connection from the plugin's connection definition.
The install switch is not here: it is platform-service's `plugins` policy, the platform admin's alone. Turning a
plugin off keeps its connection, settings and sign-ins, so turning it on again needs nothing more."""

# No `from __future__ import annotations`: FastAPI resolves the `Depends(caller)` annotations at import.

from typing import Annotated, Any, Literal, cast
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from ops_access import Access
from ops_plugin_sdk import Plugin
from ops_plugin_sdk.versions import declarations, diff, digest, tools_of
from ops_service_kit.errors import ApiError, Conflict, NotFound, ServiceUnavailable, ValidationFailed
from ops_service_kit.http import Envelope, ok

from ..auth.kinds import Kind, kind_of
from ..callers import caller_in
from ..connections.schemas import ConnectionDetail
from ..connections.service import ConnectionService, connection_rights
from ..environments import ConnectionEnvironment
from ..modules.directory import Directory
from ..modules.routes import ERRORS
from ..modules.service import Caller
from ..modules.tool_users import ToolUsers
from ..store.plugin_app_keys import PluginAppKeys
from .host import PluginHost, fixed_fields, per_environment, render, sign_in_fixed

# A credential value: a key, a password or token, or a PEM certificate or private key, the longest of them.
CREDENTIAL_MAX = 16_000


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class TeamPluginIn(_Wire):
    enabled: bool
    settings: dict[str, Any] = Field(default_factory=dict[str, Any])
    # The OAuth app the team signs in with; needed for the first turn-on of a plugin that signs in.
    client_id: str | None = Field(default=None, max_length=500)
    client_secret: str | None = Field(default=None, max_length=2000)
    sign_in: str | None = None
    # Which environment the app and the sign-in address settings are for: a sandbox has its own of both.
    environment: ConnectionEnvironment = "production"
    # Which of the plugin's sign-in kinds the team's connection uses, the first it lists when left out. It is
    # chosen at the first turn-on only: a connection's kind never changes.
    kind: str | None = Field(default=None, max_length=50)
    # The kind's own fields and the client certificate's (auth/kinds.py), secret parts included: an API key, a username
    # and password, a token, a certificate and its private key. A secret part is sealed and never answered back; one
    # left out of a later turn-on keeps its value.
    credentials: dict[str, Annotated[str, Field(max_length=CREDENTIAL_MAX)]] = Field(
        default_factory=dict[str, str], max_length=20
    )
    # The team account's name, from the Connect window; taken at the first turn-on, the app's title when left
    # out. A later rename goes through PATCH /v1/connections/{id}.
    account_name: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _app_in_credentials(self) -> "TeamPluginIn":
        """The connect dialog sends a client-credentials app as the kind's fields, inside `credentials`: the
        client id and secret given there are the app's, as when given at the top level."""
        if self.client_id is None and (cid := self.credentials.pop("clientId", None)):
            self.client_id = cid
        if self.client_secret is None and (secret := self.credentials.pop("clientSecret", None)):
            self.client_secret = secret
        return self


class AccountIn(TeamPluginIn):
    """Another account of an app the team has connected: its name, and the same turn-on contract as the
    first account's (the environment, the kind, whose account calls use, the app and the credentials)."""

    enabled: bool = True
    name: str = Field(min_length=1, max_length=200)


class FeatureOff(ApiError):
    """A route of a feature the install has not turned on: answered as if it were not there."""

    status = 404
    code = "feature_off"


class PlatformApp(_Wire):
    """The platform's own OAuth app for a plugin: its client id, and whether the account holds its secret. The secret
    itself is never shown."""

    client_id: str | None
    secret_set: bool


class AppSecretIn(_Wire):
    client_secret: str = Field(min_length=1, max_length=2000)


class PluginDisplay(_Wire):
    """The manifest's card details: a logo, a category, one line, and where to read how to set up its app."""

    logo: str | None = None
    category: str | None = None
    description: str | None = None
    docs_url: str | None = None


class PluginView(_Wire):
    id: str
    title: str
    version: str
    install_on: bool
    team_on: bool
    connection_id: str | None
    settings: dict[str, Any]
    locked: list[str]
    tools: list[str]
    knowledge_sources: list[str]
    platform_app: PlatformApp
    display: PluginDisplay = Field(default_factory=PluginDisplay)
    # The version this team runs (with plugin_updates on), and whether the installed one differs from it;
    # `version` is the installed package's.
    team_version: str | None = None
    update_available: bool = False


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


class FailedPlugin(_Wire):
    name: str
    error: str


class PluginList(_Wire):
    plugins: list[PluginView]
    failed: list[FailedPlugin]


class KnowledgeSourceView(_Wire):
    plugin: str
    source: str
    title: str
    list_tool: str
    get_tool: str
    deleted_tool: str | None
    schedule: dict[str, Any]
    connection_id: str | None
    sign_in: str | None
    # healthy, needs_reconnect, error, ...: a source paused for a reconnect resumes once Test connection passes.
    connection_status: str | None


def _shown(plugin: Plugin, settings: dict[str, Any]) -> dict[str, Any]:
    """Settings as a person may read them: a secret field never, even as its reference."""
    secret = {k for k, s in plugin.manifest.settings.items() if s.secret}
    return {k: v for k, v in settings.items() if k not in secret}


def _split(plugin: Plugin, given: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """A save's settings as the team's and the environment's own (the sign-in address): the team's stay on the
    binding, the environment's go on the connection's environment, kept there once."""
    own = per_environment(plugin.manifest)
    return {k: v for k, v in given.items() if k not in own}, {k: v for k, v in given.items() if k in own}


def plugins_router(
    host: PluginHost,
    connections: ConnectionService,
    directory: Directory,
    app_keys: PluginAppKeys,
    *,
    users: ToolUsers | None = None,
) -> APIRouter:
    """`users` answers who uses an app's tools (agents-service); without it that route answers 503, never "nobody"."""
    caller = caller_in(directory)
    access = Access(security_team=connections.security_team)
    r = APIRouter(tags=["plugins"], responses=ERRORS)

    def _plugin(plugin_id: str) -> Plugin:
        plugin = host.plugins.get(plugin_id)
        if plugin is None:
            raise NotFound(f"Plugin {plugin_id}")
        return plugin

    async def _view(who: Caller, plugin: Plugin) -> dict[str, Any]:
        m = plugin.manifest
        b = await host.bindings.get(who.tenant_id, who.team.id, m.id) or {}
        own = (await host.own_settings(who.tenant_id, b.get("connection_id"))).get("production")
        settings = await host.settings(who.tenant_id, plugin, dict(b.get("settings") or {}), "production", own)
        return PluginView(
            id=m.id,
            title=m.title,
            version=m.version,
            install_on=await host.switches.on(who.tenant_id, m.id),
            team_on=bool(b.get("enabled")),
            connection_id=b.get("connection_id"),
            settings=_shown(plugin, settings),
            locked=sorted(await host.switches.locked(who.tenant_id, m.id)),
            tools=[m.operation(t) for t in _team_tools(plugin, b)],
            knowledge_sources=[s.name for s in m.knowledge_sources],
            platform_app=PlatformApp(
                client_id=await host.switches.app_client_id(who.tenant_id, m.id),
                secret_set=await app_keys.held(who.tenant_id, m.id),
            ),
            display=PluginDisplay(**m.display.model_dump()),
            team_version=b.get("version") if host.versions else None,
            update_available=host.versions and bool(b.get("digest")) and b.get("digest") != _installed(plugin)[1],
        ).model_dump(by_alias=True)

    def _installed(plugin: Plugin) -> tuple[dict[str, Any], str]:
        decl = declarations(plugin.manifest)
        return decl, digest(decl)

    def _team_tools(plugin: Plugin, b: dict[str, Any]) -> list[str]:
        """The tool names the team's version has, else the installed manifest's."""
        if host.versions and b.get("declarations"):
            return list(tools_of(cast(dict[str, Any], b["declarations"])))
        return [t.name for t in plugin.manifest.tools]

    async def _update(who: Caller, plugin_id: str) -> tuple[Plugin, dict[str, Any]]:
        """The plugin and the team's binding, for a team admin, with plugin_updates on (404 otherwise)."""
        if not host.versions:
            raise NotFound("Plugin updates are off for this install")
        if who.principal is not None:
            connection_rights(who.principal, "manage", security_team=connections.security_team, what="plugins")
        plugin = _plugin(plugin_id)
        b = await host.bindings.get(who.tenant_id, who.team.id, plugin.manifest.id)
        if b is None:
            raise NotFound(f"{plugin.manifest.title} is not turned on for this team")
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

    def _account_admin(who: Caller) -> str:
        """settings.manage in the Security team: an account admin, never a team admin."""
        if who.principal is None:
            raise ValidationFailed("Only an account admin sets the platform's app.", code="admin_only")
        access.can(who.principal, "settings", "manage", what="the platform's plugin apps", code="admin_only")
        return who.name

    @r.get("/v1/plugins", response_model=Envelope[PluginList])
    async def list_plugins(who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The installed plugins as this team sees them, and the ones that failed to load with why."""
        return ok(
            PluginList(
                plugins=[PluginView(**await _view(who, p)) for p in host.plugins.values()],
                failed=[FailedPlugin(name=i.name, error=i.error or "") for i in host.loaded if not i.ok],
            ).model_dump(by_alias=True)
        )

    @r.put("/v1/plugins/{plugin_id}/app-secret", response_model=Envelope[PluginView])
    async def set_app_secret(  # pyright: ignore[reportUnusedFunction]
        plugin_id: str, body: AppSecretIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Seals the platform's own OAuth app secret for the plugin at the account. Its client id is in the
        plugins policy; a team with no app of its own signs in with this one. The answer never carries the secret."""
        by = _account_admin(who)
        plugin = _plugin(plugin_id)
        await app_keys.save(who.tenant_id, plugin.manifest.id, body.client_secret, by=by)
        return ok(await _view(who, plugin))

    @r.delete("/v1/plugins/{plugin_id}/app-secret", response_model=Envelope[PluginView])
    async def delete_app_secret(  # pyright: ignore[reportUnusedFunction]
        plugin_id: str, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Removes the platform's app secret: teams on the platform's app cannot sign in again until it is set."""
        _account_admin(who)
        plugin = _plugin(plugin_id)
        await app_keys.delete(who.tenant_id, plugin.manifest.id)
        return ok(await _view(who, plugin))

    @r.put("/v1/plugins/{plugin_id}/team", response_model=Envelope[PluginView])
    async def set_team_plugin(  # pyright: ignore[reportUnusedFunction]
        plugin_id: str, body: TeamPluginIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Turns the plugin on or off for the team and saves the team's settings: a team admin's alone."""
        if who.principal is not None:
            connection_rights(who.principal, "manage", security_team=connections.security_team, what="plugins")
        plugin = _plugin(plugin_id)
        m = plugin.manifest
        locked = await host.switches.locked(who.tenant_id, m.id)
        for k in body.settings:
            setting = m.settings.get(k)
            if setting is None:
                raise ValidationFailed(f"{k} is not a setting of {m.title}.", details={"field": k})
            if k in locked:
                raise ValidationFailed(f"{k} is set by the platform admin for every team.", code="setting_locked")
            if setting.at_sign_in:
                raise ValidationFailed(f"{k} is read from the sign-in, not typed.", code="setting_from_token")
        before = await host.bindings.get(who.tenant_id, who.team.id, m.id) or {}
        team, own = _split(plugin, body.settings)
        # The binding keeps the team's settings only: an environment's own are its connection's, so a copy
        # left from before (a removed connection's instance) never reaches a call.
        mine = per_environment(m)
        held = dict(before.get("settings") or {})
        settings = {k: v for k, v in held.items() if k != "environments" and k not in mine} | team
        connection_id = before.get("connection_id")
        if connection_id is not None and await connections.store.get(who.tenant_id, str(connection_id)) is None:
            # Removed, as the connect dialog's Cancel removes the one it made: the next turn-on makes another.
            connection_id = None
        if body.enabled and connection_id is None:
            connection_id = await _connect(who, plugin, settings, own, body, account_name=body.account_name)
        elif body.enabled and (
            body.client_id
            or body.client_secret
            or body.credentials
            or body.kind
            or own
            or body.environment not in await _set(who, connection_id)
        ):
            # The connection exists: this PUT sets the named environment's app on it, a sandbox beside
            # production, instead of being dropped as it was when only the first turn-on built the connection.
            await _environment(who, plugin, str(connection_id), settings, body, own=own)
        await host.bindings.put(
            who.tenant_id,
            who.team.id,
            m.id,
            enabled=body.enabled,
            connection_id=connection_id,
            settings=settings,
            by=who.name,
        )
        if host.versions and not before.get("version"):
            # A team turning a plugin on takes the installed version; a later upgrade waits for its review.
            await host.take_installed(who.tenant_id, who.team.id, plugin)
        return ok(await _view(who, plugin))

    @r.get("/v1/plugins/{plugin_id}/team/users", response_model=Envelope[AppUsers])
    async def app_users(plugin_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The team's agents and workflows that use the app's tools, each with the tools it uses: what turning the app
        off stops. A team admin's, as turning it off is."""
        if who.principal is not None:
            connection_rights(who.principal, "manage", security_team=connections.security_team, what="plugins")
        plugin = _plugin(plugin_id)
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

    @r.post("/v1/plugins/{plugin_id}/accounts", response_model=Envelope[ConnectionDetail], status_code=201)
    async def add_account(  # pyright: ignore[reportUnusedFunction]
        plugin_id: str, body: AccountIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Another named account of an app the team has connected (with several_accounts on): a second org or a
        second account of the same system, made with the first's contract. The first stays the default."""
        if not host.accounts:
            raise FeatureOff("Several accounts of one app are not turned on for this install.")
        if who.principal is not None:
            connection_rights(who.principal, "manage", security_team=connections.security_team, what="plugins")
        plugin = _plugin(plugin_id)
        m = plugin.manifest
        b = await host.bindings.get(who.tenant_id, who.team.id, m.id)
        if b is None or not b["enabled"] or not b.get("connection_id"):
            raise ValidationFailed(f"Connect {m.title} first; another account comes after it.", code="no_first_account")
        name = body.name.strip()
        if not name:
            raise ValidationFailed("Name the account.", details={"field": "name"})
        if await host.account_named(who.tenant_id, who.team.id, plugin, name) is not None:
            raise Conflict(f"{m.title} already has an account named {name}.")
        team, own = _split(plugin, body.settings)
        mine = per_environment(m)
        held = dict(b.get("settings") or {})
        settings = {k: v for k, v in held.items() if k != "environments" and k not in mine} | team
        made = await _connect(who, plugin, settings, own, body, account_name=name)
        return ok(await connections.detail(who, made), 201)

    def _kind(plugin: Plugin, body: TeamPluginIn) -> Kind:
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

    def _credentials(plugin: Plugin, kind: Kind, given: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        """The credentials split into plain settings and secret parts, each a field of the kind or of the client
        certificate; any other name is refused rather than dropped, so a typo never leaves a connection unsigned. A
        field the plugin sets itself (its addresses, its permissions) is refused too: it would replace the plugin's."""
        plain: dict[str, str] = {}
        secret: dict[str, str] = {}
        fixed = {"baseUrl", "testPath", *fixed_fields(plugin.manifest)}
        for k, v in given.items():
            f = kind.field(k)
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

    async def _connect(
        who: Caller,
        plugin: Plugin,
        settings: dict[str, Any],
        own: dict[str, Any],
        body: TeamPluginIn,
        *,
        account_name: str | None = None,
    ) -> str:
        """The team's connection, from the plugin's definition, made whole in one call for every kind: its
        address, its test path, how its key is sent, the credentials the team gave, and for a kind that holds a token
        the OAuth app and its addresses. An instance the token names comes later, at sign-in."""
        m = plugin.manifest
        c = m.connection
        kind = _kind(plugin, body)
        sign_in = body.sign_in or c.sign_in[0]
        if sign_in not in c.sign_in:
            raise ValidationFailed(f"{m.title} signs in with {', '.join(c.sign_in)}.", code="sign_in_not_offered")
        plain, secret = _credentials(plugin, kind, body.credentials)
        # A token kind's client secret comes from the team's own app or the platform's, checked when it is used.
        # On a connection each person signs in to, their own key, password or token is theirs to give.
        each_person = sign_in == "person" and kind.per_person
        missing = [
            f.label
            # The plugin's own clientAuth counts, so one that signs an assertion asks for the signing pair.
            for f in kind.requires({**plain, **sign_in_fixed(plugin.manifest)}, each_person=each_person)
            if f.secret and f.name not in secret and not (kind.holds_token and f.name == "clientSecret")
        ]
        if kind.holds_token and not body.client_id and not await host.switches.app_client_id(who.tenant_id, m.id):
            raise ValidationFailed(
                f"Give the OAuth app's client id to turn {m.title} on, or ask an account admin to set up "
                "the platform's app for it.",
                code="client_missing",
            )
        if missing:
            raise ValidationFailed(f"{m.title} needs {', '.join(missing)} to sign in with {kind.label}.")
        # The same create contract as a connection made by name (cross-card review): the row carries the
        # system's card details from the manifest, so a plugin's connection and one made by hand hold the same columns.
        shown = m.display
        made = await connections.create(
            who,
            {
                "name": account_name or m.title,
                # The app's account: the plugin it belongs to, and its name, the app's title for the first.
                "plugin_id": m.id,
                "account_name": account_name or m.title,
                "auth_kind": kind.id,
                "sign_in": sign_in if kind.per_person else "team",
                "category": shown.category,
                "description": shown.description,
                "docs_url": shown.docs_url,
            },
        )
        try:
            await _environment(who, plugin, str(made["id"]), settings, body, own=own)
        except ValidationFailed:
            # A connection the team cannot use is not left behind for the next turn-on to trip over.
            await connections.delete(who, str(made["id"]))
            raise
        return str(made["id"])

    async def _set(who: Caller, connection_id: Any) -> set[str]:
        conn = await connections.store.get(who.tenant_id, str(connection_id))
        return set(conn["environments"]) if conn else set()

    async def _environment(
        who: Caller,
        plugin: Plugin,
        connection_id: str,
        settings: dict[str, Any],
        body: TeamPluginIn,
        *,
        own: dict[str, Any],
    ) -> None:
        """One environment of the plugin's connection: the system's address (the endpoint's origin, or the sign-in
        host's until the token names the instance), the health check as Test connection's path, how an API key is
        sent, the team's credentials over what the environment already holds, and for a kind that holds a token the
        OAuth app (the team's own first, else the platform's, set up once by an account admin) and its
        addresses, rendered with that environment's settings."""
        m = plugin.manifest
        c = m.connection
        environment = body.environment
        conn = await connections.store.get(who.tenant_id, connection_id)
        kind = kind_of(str(conn["auth_kind"])) if conn else _kind(plugin, body)
        if body.kind and body.kind != kind.id:
            raise ValidationFailed(
                f"{m.title}'s connection signs in with {kind.label}; its kind is chosen once, when it is made.",
                code="kind_fixed",
                details={"field": "kind"},
            )
        plain, secret = _credentials(plugin, kind, body.credentials)
        envs = cast(dict[str, dict[str, Any]], (conn or {}).get("environments") or {})
        held = dict(envs.get(environment) or {})
        # The environment's own settings, those given over those it holds, kept on its row of the connection.
        mine = {**dict(held.get("plugin_settings") or {}), **own}
        merged = await host.settings(who.tenant_id, plugin, settings, environment, mine)
        before = cast(dict[str, Any], held.get("settings") or {})
        env: dict[str, Any] = dict(before)
        endpoint = render(m.endpoint, merged)
        platform_id: str | None = None
        if kind.holds_token:
            # A later turn-on that names no app keeps the team's own; else the platform's.
            keep_own = not body.client_id and not body.client_secret and bool(before.get("clientId"))
            keep_own = keep_own and not held.get("platform_app")
            if not body.client_id and not keep_own:
                platform_id = await host.switches.app_client_id(who.tenant_id, m.id)
            client_id = body.client_id or (before.get("clientId") if keep_own else platform_id)
            if not client_id:
                raise ValidationFailed(
                    f"Give the OAuth app's client id to turn {m.title} on, or ask an account admin to set up "
                    "the platform's app for it.",
                    code="client_missing",
                )
            env |= {"clientId": client_id, "scopes": " ".join(s.id for s in c.scopes)}
            for key, template in (
                ("authorizeUrl", c.authorize_url),
                ("tokenUrl", c.token_url),
                ("revokeUrl", c.revoke_url),
            ):
                if template and kind.field(key) is not None:
                    value = render(template, merged)
                    if value is None:
                        raise ValidationFailed(f"Set {m.title}'s settings its sign-in addresses need first.")
                    env[key] = value
            if c.client_auth and kind.field("clientAuth") is not None:
                env["clientAuth"] = c.client_auth
            if c.authorize_params and kind.field("authorizeParams") is not None:
                params = {k: render(v, merged) for k, v in c.authorize_params.items()}
                if any(v is None for v in params.values()):
                    raise ValidationFailed(f"Set {m.title}'s settings its sign-in parameters need first.")
                env["authorizeParams"] = urlencode(params)
        # Credentials go to the system's address only: the endpoint's origin, or before the token names the instance,
        # the sign-in host's, which the sign-in replaces (host.on_token).
        base = endpoint or render(c.authorize_url or "", merged)
        if not base:
            raise ValidationFailed(f"Set {m.title}'s settings its address needs first.")
        parts = urlsplit(base)
        env["baseUrl"] = f"{parts.scheme}://{parts.netloc}"
        check = c.health_check
        path = render(check.path, merged) if check and endpoint else None
        if path:
            env["testPath"] = path
        if kind.id == "api_key" and c.api_key is not None:
            env |= {"placement": c.api_key.placement, "name": c.api_key.name}
        env |= plain
        if platform_id is not None:
            await connections.use_platform_app(who, connection_id, environment, m.id, env, plugin_settings=mine)
            return
        values = {**secret, **({"clientSecret": body.client_secret} if body.client_secret else {})}
        await connections.set_environment(
            who,
            connection_id,
            environment,
            {"revision": int(conn["revision"]) if conn else 1, "settings": env, "secret_values": values},
            plugin_settings=mine,
        )

    @r.get("/v1/plugins/{plugin_id}/team/update", response_model=Envelope[PluginUpdateView])
    async def plugin_update(plugin_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """What taking the installed plugin version would change for the team: each new, changed and removed tool."""
        plugin, b = await _update(who, plugin_id)
        return ok(_review(plugin, b))

    @r.post("/v1/plugins/{plugin_id}/team/update", response_model=Envelope[PluginUpdateView])
    async def take_plugin_update(  # pyright: ignore[reportUnusedFunction]
        plugin_id: str, body: TakeUpdateIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Takes the installed version for the team, from its next call. The digest is the one the review was read
        at, so a review another upgrade has replaced since is refused rather than taken unseen."""
        plugin, _ = await _update(who, plugin_id)
        if body.digest != _installed(plugin)[1]:
            raise Conflict(
                f"{plugin.manifest.title} changed again since this review; read the update again.",
                code="update_changed",
            )
        await host.take_installed(who.tenant_id, who.team.id, plugin)
        b = await host.bindings.get(who.tenant_id, who.team.id, plugin.manifest.id) or {}
        return ok(_review(plugin, b))

    @r.get("/v1/knowledge-sources", response_model=Envelope[list[KnowledgeSourceView]])
    async def knowledge_sources(who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The knowledge sources a team can create from its plugins that are on, with the connection each would read
        through: kb-service lists them and syncs by calling the two tools named here."""
        out: list[dict[str, Any]] = []
        for plugin in host.plugins.values():
            m = plugin.manifest
            if await host.off_reason(who.tenant_id, who.team.id, plugin) is not None:
                continue
            b = await host.bindings.get(who.tenant_id, who.team.id, m.id) or {}
            conn = None
            if b.get("connection_id"):
                conn = await connections.store.get(who.tenant_id, str(b["connection_id"]))
            for s in m.knowledge_sources:
                out.append(
                    KnowledgeSourceView(
                        plugin=m.id,
                        source=s.name,
                        title=s.title,
                        list_tool=m.operation(s.list),
                        get_tool=m.operation(s.get),
                        deleted_tool=m.operation(s.deleted) if s.deleted else None,
                        schedule=s.schedule.model_dump(),
                        connection_id=b.get("connection_id"),
                        sign_in=(conn or {}).get("sign_in"),
                        connection_status=(conn or {}).get("status"),
                    ).model_dump(by_alias=True)
                )
        return ok(out)

    return r
