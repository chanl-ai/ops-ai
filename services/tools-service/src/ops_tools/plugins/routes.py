"""`/v1/plugins` and `/v1/knowledge-sources` (c-564): what a team sees of the installed plugins and turns on.

A team admin (connections.manage in the team) turns a plugin on or off for the team, gives its settings and the OAuth
app the team signs in with; the first turn-on makes the team's connection from the plugin's connection definition.
The install switch is not here: it is platform-service's `plugins` policy, the platform admin's alone. Turning a
plugin off keeps its connection, settings and sign-ins, so turning it on again needs nothing more."""

# No `from __future__ import annotations`: FastAPI resolves the `Depends(caller)` annotations at import.

from typing import Annotated, Any, Literal, cast
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_access import Access
from ops_plugin_sdk import Plugin
from ops_service_kit.errors import NotFound, ValidationFailed
from ops_service_kit.http import Envelope, ok

from ..auth.kinds import Kind, kind_of
from ..callers import caller_in
from ..connections.service import ConnectionService, connection_rights
from ..modules.directory import Directory
from ..modules.routes import ERRORS
from ..modules.service import Caller
from ..store.plugin_app_keys import PluginAppKeys
from .host import PluginHost, per_environment, render

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
    # Which environment the app and the sign-in address settings are for (c-580): a sandbox has its own of both.
    environment: Literal["test", "production"] = "production"
    # Which of the plugin's sign-in kinds the team's connection uses, the first it lists when left out (c-588). It is
    # chosen at the first turn-on only: a connection's kind never changes.
    kind: str | None = Field(default=None, max_length=50)
    # The kind's own fields and the client certificate's (auth/kinds.py), secret parts included: an API key, a username
    # and password, a token, a certificate and its private key. A secret part is sealed and never answered back; one
    # left out of a later turn-on keeps its value.
    credentials: dict[str, Annotated[str, Field(max_length=CREDENTIAL_MAX)]] = Field(
        default_factory=dict[str, str], max_length=20
    )


class PlatformApp(_Wire):
    """The platform's own OAuth app for a plugin: its client id, and whether the account holds its secret. The secret
    itself is never shown."""

    client_id: str | None
    secret_set: bool


class AppSecretIn(_Wire):
    client_secret: str = Field(min_length=1, max_length=2000)


class PluginDisplay(_Wire):
    """The manifest's card details (c-580): a logo, a category, one line, and where to read how to set up its app."""

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


def _saved(plugin: Plugin, before: dict[str, Any], given: dict[str, Any], environment: str) -> dict[str, Any]:
    """The team's settings after a save: a setting each environment keeps its own (the sign-in address, c-580) goes
    under `environments.<environment>`, the rest stay the team's."""
    own = per_environment(plugin.manifest)
    envs = {k: dict(v) for k, v in dict(before.get("environments") or {}).items()}
    envs[environment] = {**(envs.get(environment) or {}), **{k: v for k, v in given.items() if k in own}}
    # Production's also stay at the top level, where a binding from before kept them.
    team = {k: v for k, v in given.items() if k not in own or environment == "production"}
    return {**before, **team, "environments": envs}


def plugins_router(
    host: PluginHost, connections: ConnectionService, directory: Directory, app_keys: PluginAppKeys
) -> APIRouter:
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
        settings = await host.settings(who.tenant_id, plugin, dict(b.get("settings") or {}))
        return PluginView(
            id=m.id,
            title=m.title,
            version=m.version,
            install_on=await host.switches.on(who.tenant_id, m.id),
            team_on=bool(b.get("enabled")),
            connection_id=b.get("connection_id"),
            settings=_shown(plugin, settings),
            locked=sorted(await host.switches.locked(who.tenant_id, m.id)),
            tools=[m.operation(t.name) for t in m.tools],
            knowledge_sources=[s.name for s in m.knowledge_sources],
            platform_app=PlatformApp(
                client_id=await host.switches.app_client_id(who.tenant_id, m.id),
                secret_set=await app_keys.held(who.tenant_id, m.id),
            ),
            display=PluginDisplay(**m.display.model_dump()),
        ).model_dump(by_alias=True)

    def _account_admin(who: Caller) -> str:
        """settings.manage in the Security team: an account admin, never a team admin (c-565)."""
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
        """Seals the platform's own OAuth app secret for the plugin at the account (c-565). Its client id is in the
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
            if setting.from_token:
                raise ValidationFailed(f"{k} is read from the sign-in, not typed.", code="setting_from_token")
        before = await host.bindings.get(who.tenant_id, who.team.id, m.id) or {}
        settings = _saved(plugin, dict(before.get("settings") or {}), body.settings, body.environment)
        connection_id = before.get("connection_id")
        if body.enabled and connection_id is None:
            connection_id = await _connect(who, plugin, settings, body)
        elif body.enabled and (
            body.client_id
            or body.client_secret
            or body.credentials
            or body.kind
            or body.environment not in await _set(who, connection_id)
        ):
            # The connection exists (c-580): this PUT sets the named environment's app on it, a sandbox beside
            # production, instead of being dropped as it was when only the first turn-on built the connection.
            await _environment(who, plugin, str(connection_id), settings, body)
        await host.bindings.put(
            who.tenant_id,
            who.team.id,
            m.id,
            enabled=body.enabled,
            connection_id=connection_id,
            settings=settings,
            by=who.name,
        )
        return ok(await _view(who, plugin))

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

    def _credentials(kind: Kind, given: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        """The credentials split into plain settings and secret parts, each a field of the kind or of the client
        certificate; any other name is refused rather than dropped, so a typo never leaves a connection unsigned."""
        plain: dict[str, str] = {}
        secret: dict[str, str] = {}
        for k, v in given.items():
            f = kind.field(k)
            if f is None or k in ("baseUrl", "testPath"):
                raise ValidationFailed(
                    f"{k} is not part of signing in with {kind.label}.", details={"field": f"credentials.{k}"}
                )
            (secret if f.secret else plain)[k] = v
        return plain, secret

    async def _connect(who: Caller, plugin: Plugin, settings: dict[str, Any], body: TeamPluginIn) -> str:
        """The team's connection, from the plugin's definition, made whole in one call for every kind (c-588): its
        address, its test path, how its key is sent, the credentials the team gave, and for a kind that holds a token
        the OAuth app and its addresses. An instance the token names comes later, at sign-in."""
        m = plugin.manifest
        c = m.connection
        kind = _kind(plugin, body)
        sign_in = body.sign_in or c.sign_in[0]
        if sign_in not in c.sign_in:
            raise ValidationFailed(f"{m.title} signs in with {', '.join(c.sign_in)}.", code="sign_in_not_offered")
        plain, secret = _credentials(kind, body.credentials)
        # A token kind's client secret comes from the team's own app or the platform's, checked when it is used.
        missing = [
            f.label
            for f in kind.requires(plain)
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
        made = await connections.create(
            who, {"name": m.title, "auth_kind": kind.id, "sign_in": sign_in if kind.per_person else "team"}
        )
        try:
            await _environment(who, plugin, str(made["id"]), settings, body)
        except ValidationFailed:
            # A connection the team cannot use is not left behind for the next turn-on to trip over.
            await connections.delete(who, str(made["id"]))
            raise
        return str(made["id"])

    async def _set(who: Caller, connection_id: Any) -> set[str]:
        conn = await connections.store.get(who.tenant_id, str(connection_id))
        return set(conn["environments"]) if conn else set()

    async def _environment(
        who: Caller, plugin: Plugin, connection_id: str, settings: dict[str, Any], body: TeamPluginIn
    ) -> None:
        """One environment of the plugin's connection: the system's address (the endpoint's origin, or the sign-in
        host's until the token names the instance), the health check as Test connection's path, how an API key is
        sent, the team's credentials over what the environment already holds, and for a kind that holds a token the
        OAuth app (the team's own first, else the platform's, set up once by an account admin, c-565) and its
        addresses, rendered with that environment's settings (c-580)."""
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
        plain, secret = _credentials(kind, body.credentials)
        merged = await host.settings(who.tenant_id, plugin, settings, environment)
        envs = cast(dict[str, dict[str, Any]], (conn or {}).get("environments") or {})
        held = dict(envs.get(environment) or {})
        saved = cast(dict[str, Any], held.get("settings") or {})
        before = {k: v for k, v in saved.items() if k != "platformApp"}
        env: dict[str, Any] = dict(before)
        endpoint = render(m.endpoint, merged)
        platform_id: str | None = None
        if kind.holds_token:
            # A later turn-on that names no app keeps the team's own; else the platform's.
            keep_own = not body.client_id and not body.client_secret and bool(before.get("clientId"))
            keep_own = keep_own and not saved.get("platformApp")
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
            await connections.use_platform_app(who, connection_id, environment, m.id, env)
            return
        values = {**secret, **({"clientSecret": body.client_secret} if body.client_secret else {})}
        await connections.set_environment(
            who,
            connection_id,
            environment,
            {"revision": int(conn["revision"]) if conn else 1, "settings": env, "secret_values": values},
        )

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
