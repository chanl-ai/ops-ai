"""The plugins this tools-service loaded at start, the module each one is, and each call's view of it (c-564).

Each loaded plugin is one workspace-level tool module (no team owns it, c-433) whose operations are its tools, named
`<plugin>_<tool>`, so grants, approval, OPA, the call log and MCP treat them as any tool. The module row holds no
connection, endpoint or egress list: `for_call` fills those from the calling team's binding and accounts on every call,
so two teams running the same plugin reach their own Salesforce org with their own sign-in. An installed plugin is off
for a team until the team turns it on (its binding)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

import httpx

from ops_plugin_sdk import Manifest, Plugin
from ops_plugin_sdk.loader import Loaded, discover
from ops_plugin_sdk.manifest import AfterSignIn, InputField, Tool
from ops_plugin_sdk.paging import at
from ops_plugin_sdk.paging import headers as request_headers
from ops_plugin_sdk.versions import declarations, digest, tools_of
from ops_plugin_sdk.versions import headers_of as declared_headers
from ops_service_kit.logging import get_logger
from ops_service_kit.settings import Settings

from ..connections.records import account_for
from ..egress import EgressDenied, EgressPolicy, for_tenant
from ..modules.seed import blank
from ..store.connections import ConnectionStore, plugin_app, plugin_of
from ..store.modules import Aggregate, ModuleStore, StaleModuleError
from ..store.plugin_bindings import PluginBindings

log = get_logger("ops_tools.plugins")

TEMPLATE_PREFIX = "plugin:"
PLACE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
# A value a header may not carry: `{{` would be resolved as one of the tenant's secrets by the http executor
# (executor.SECRET_REF), and a line break would start another header.
UNSENDABLE = re.compile(r"\{\{|[\r\n]")
# A looked-up value that is not an address goes into an address where it is rendered (Atlassian's cloud id in the
# endpoint's path), so it may hold nothing that adds a path segment or a query.
PLAIN_VALUE = re.compile(r"^[A-Za-z0-9._:-]+$")
LOOKUP_TIMEOUT_S = 10.0


class SignInRefused(ValueError):
    """A sign-in the plugin refuses, with the code its sign-in event records: `token_host`, `lookup_failed` or
    `another_site`. A ValueError, so the connection service fails the sign-in before it stores any token."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def settle_at_sign_in(held: Mapping[str, Any], read: Mapping[str, Any], *, own: bool) -> dict[str, Any]:
    """Whose sign-in may set a setting filled at sign-in (the instance, the site): the team's own sign-in sets or
    replaces it; a person's own sets it only when the account holds none, and one that reads a different value is
    refused, so one person cannot point the team's calls at another tenant. The one place this rule lives, so the
    sign-in design for chat users, Entra and Salesforce can change it alone."""
    for name, value in read.items():
        before = held.get(name)
        if own and before not in (None, "") and before != value:
            raise SignInRefused(
                f"signed in to another site: this account reaches {value}, the team's connection reaches {before}; "
                "sign in with an account on the team's site",
                "another_site",
            )
    return dict(read)


def readable(manifest: Manifest, settings: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, bool]]:
    """Settings as a person may read them: each plain value, and for a secret one only whether it is set, never even
    its reference."""
    secret = {k for k, s in manifest.settings.items() if s.secret}
    plain = {k: v for k, v in settings.items() if k not in secret}
    return plain, {k: settings.get(k) not in (None, "") for k in sorted(secret)}


def hosts_of(manifest: Manifest, settings: Mapping[str, Any]) -> list[str]:
    """The plugin's egress hosts rendered with the settings; one whose setting is unset is left out."""
    return [urlsplit(h).hostname or h for h in (render(e, settings) for e in manifest.egress) if h]


def module_id_of(manifest: Manifest) -> str:
    return f"mod_plugin_{manifest.short}"


def plugin_id_of(module: Mapping[str, Any]) -> str | None:
    """The plugin a module is, from its template slot; None for every other module."""
    slot = str(module.get("template_id") or "")
    return slot.removeprefix(TEMPLATE_PREFIX) if slot.startswith(TEMPLATE_PREFIX) else None


def render(text: str, settings: Mapping[str, Any]) -> str | None:
    """`{name}` from the settings; None while one is unset (an instance not yet read from the token)."""
    missing = [n for n in PLACE.findall(text) if settings.get(n) in (None, "")]
    if missing:
        return None
    return PLACE.sub(lambda m: str(settings[m.group(1)]), text)


def header_settings(headers: Mapping[str, str], tools: Iterable[Tool]) -> set[str]:
    """The settings any of a plugin version's headers render, plugin-wide or a tool's."""
    texts = [*headers.values(), *(v for t in tools for v in t.headers.values())]
    return {n for t in texts for n in PLACE.findall(t)}


def headers_of(headers: Mapping[str, str], tool: Tool, settings: Mapping[str, Any]) -> list[dict[str, str]]:
    """A call's headers as a module operation holds them (`{key, value}`): the plugin's, then the tool's over them,
    rendered from the call's settings. A header whose setting is unset is left out. The kit's own rule, so `ops plugin
    test` sends the same headers."""
    return [{"key": k, "value": v} for k, v in request_headers(headers, tool, settings).items()]


CURSOR = {
    "name": "cursor",
    "type": "string",
    "required": False,
    "description": "The next_cursor a previous page answered, for the page after it",
}


_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def per_account(manifest: Manifest) -> set[str]:
    """The settings each account keeps its own (c-580): those read from the token (the instance) and those the sign-in
    addresses name (Salesforce's login_url), since a sandbox signs in elsewhere and lands elsewhere."""
    c = manifest.connection
    named = {n for t in (c.authorize_url, c.token_url, c.revoke_url) if t for n in _PLACEHOLDER.findall(t)}
    looked = {c.after_sign_in.setting} if c.after_sign_in else set[str]()
    return (set(c.from_token) | named | looked) & set(manifest.settings)


def fixed_fields(manifest: Manifest) -> list[str]:
    """The sign-in kinds' fields the plugin sets itself (c-580): how its key is sent, its sign-in, token and revocation
    addresses, and the permissions it asks for. A team is never asked for one, and a typed one is refused, since it
    would replace the plugin's and send the credential elsewhere."""
    c = manifest.connection
    named = {"authorizeUrl": c.authorize_url, "tokenUrl": c.token_url, "revokeUrl": c.revoke_url}
    fixed = {k for k, template in named.items() if template}
    if c.scopes:
        fixed.add("scopes")
    if c.api_key is not None:
        fixed |= {"placement", "name"}
    return sorted(fixed | set(sign_in_fixed(manifest)))


def sign_in_fixed(manifest: Manifest) -> dict[str, str]:
    """The token call's and sign-in address's settings the plugin fixes (c-584): how its client is sent, and its extra
    sign-in parameters, held URL-encoded as the connection's `authorizeParams`."""
    c = manifest.connection
    out: dict[str, str] = {}
    if c.client_auth:
        out["clientAuth"] = c.client_auth
    if c.authorize_params:
        out["authorizeParams"] = urlencode(c.authorize_params)
    return out


def checked(tool: Tool) -> bool:
    """Whether a data tool needs the plugin executor: it pages, builds a query, or has inputs to check before any
    request leaves. Every other data tool runs on the http executor as any module's operation does."""
    req = tool.request
    if req is None:
        return False
    return bool(req.query or req.paging) or any(
        f.enum is not None or f.format or f.pattern or f.properties or f.items for f in tool.input.values()
    )


def input_field(name: str, f: InputField, *, paged: bool = False) -> dict[str, Any]:
    """An input as the gateway checks a call against it. A paged tool's inputs are all optional there: its next page
    is asked with the cursor alone, and the plugin executor checks a first page's required inputs."""
    out: dict[str, Any] = {
        "name": name,
        "type": f.type,
        "required": f.required and not paged,
        "description": f.description,
    }
    if f.default is not None:
        out["default"] = f.default
    if f.enum is not None and all(isinstance(v, str) for v in f.enum):
        out["enum"] = list(f.enum)
    if f.format:
        out["format"] = f.format
    return out


def operation_of(m: Manifest, t: Tool, op_id: str) -> dict[str, Any]:
    """One tool as a module operation: on the http executor for a plain data tool, on the plugin executor for one that
    pages, checks its inputs or is Python. Built for the module row and, per call, from the team's version (c-609)."""
    return {
        "id": op_id,
        "tool_id": f"tl_{m.operation(t.name)}",
        "name": m.operation(t.name),
        "description": t.description or t.name.replace("_", " "),
        "access": t.access,
        "enabled": True,
        "executor": "plugin" if t.function or checked(t) else "http",
        "method": t.request.method if t.request else None,
        "path": t.request.path if t.request else None,
        "headers": [],
        "body": t.request.body if t.request else None,
        "response_transform": t.transform,
        "input": [input_field(n, f, paged=bool(t.request and t.request.paging)) for n, f in t.input.items()]
        + ([CURSOR] if t.request and t.request.paging and "cursor" not in t.input else []),
        "masked_output": [],
        "binding": None,
        "rate_limit_per_min": t.rate_limit_per_min,
        "requires_approval": t.waits,
        "approvers": 1,
        "amount_max": t.amount_max,
        "needs_person": t.needs_person,
        "scopes": list(t.scopes),
        "stub": {"ok": True},
    }


def following(m: Manifest, row_ops: Sequence[Mapping[str, Any]], kept: Iterable[Tool] = ()) -> list[dict[str, Any]]:
    """The module row's operations for the installed manifest (c-609): each tool keeps the id of the row's operation
    with its name, a new tool takes the next id above the highest, and a tool the manifest dropped stays as its row,
    switched off, so a team whose version still has it keeps calling it and grants naming its id stay true. `kept` are
    the tools a team's version still declares; one the row never held (written first by this version) is added
    switched off too, so the team's calls find it."""
    ids = {str(o["name"]): str(o["id"]) for o in row_ops}
    taken = [int(n) for i in ids.values() if (n := i.rsplit("_op", 1)[-1]).isdigit()]
    after = max(taken, default=0)

    def next_id(name: str) -> str:
        nonlocal after
        if name in ids:
            return ids[name]
        after += 1
        ids[name] = f"{module_id_of(m)}_op{after}"
        return ids[name]

    out = [operation_of(m, t, next_id(m.operation(t.name))) for t in m.tools]
    installed = {m.operation(t.name) for t in m.tools}
    out += [{**dict(o), "enabled": False} for o in row_ops if str(o["name"]) not in installed]
    held = installed | {str(o["name"]) for o in row_ops}
    for t in kept:
        name = m.operation(t.name)
        if name not in held:
            held.add(name)
            out.append({**operation_of(m, t, next_id(name)), "enabled": False})
    return out


def module_of(plugin: Plugin, *, tenant_id: str, at: datetime) -> Aggregate:
    """The plugin as one published workspace-level module: data tools on the http executor, Python tools on the
    plugin executor. It holds no address: a call renders the manifest's with the team's settings."""
    m = plugin.manifest
    mod = blank(
        module_id=module_id_of(m),
        tenant_id=tenant_id,
        team_id=None,
        owner="Plugins",
        me="tools-service",
        at=at,
        input={"displayName": m.title, "name": f"plugin-{m.short}", "type": "http"},
    )
    ops = [operation_of(m, t, f"{module_id_of(m)}_op{i + 1}") for i, t in enumerate(m.tools)]
    version = {**mod["versions"][0], "id": f"{module_id_of(m)}_v{m.version}", "version": m.version, "major": 1}
    version.update(status="published", published_at=at, note=f"{m.title} plugin {m.version}")
    return {
        **mod,
        "status": "published",
        "system": m.title,
        "description": f"The {m.title} plugin's tools ({m.id} {m.version}).",
        "template_id": f"{TEMPLATE_PREFIX}{m.id}",
        # Nobody edits it: its tools change only with the installed package (and every write route refuses it).
        "protection": "system",
        "version": m.version,
        "operations": ops,
        "versions": [version],
    }


@dataclass
class PluginHost:
    store: ModuleStore
    bindings: PluginBindings
    # The settings the install fixes for every team, per plugin (plugin_locked in the install config).
    locked: Mapping[str, Mapping[str, Any]] = field(default_factory=dict[str, Mapping[str, Any]])
    loaded: list[Loaded] = field(default_factory=list[Loaded])
    # Where each account's own plugin settings are kept (c-580): on the account itself.
    connections: ConnectionStore | None = None
    # The egress client and policy the lookup after sign-in goes through, as any call does (c-584).
    http: httpx.AsyncClient | None = None
    policy: EgressPolicy | None = None
    # The plugin_updates flag (c-609): each team runs the plugin version it took. Off, the row is written once and
    # every call reads the installed manifest, as before.
    versions: bool = False
    # The several_accounts flag (c-608): a team keeps several named accounts of one app, and a call may name one.
    accounts: bool = False
    _written: set[str] = field(default_factory=set[str])

    @classmethod
    def start(
        cls,
        store: ModuleStore,
        bindings: PluginBindings,
        locked: Mapping[str, Mapping[str, Any]],
        folders: Sequence[str] = (),
        connections: ConnectionStore | None = None,
        *,
        http: httpx.AsyncClient | None = None,
        policy: EgressPolicy | None = None,
        versions: bool = False,
        accounts: bool = False,
    ) -> PluginHost:
        """Reads every installed plugin once, at start, and the developer's plugin folders; a failed one is left out and
        logged with why, where the install's admin reads it."""
        loaded = discover(folders=folders)
        for item in loaded:
            if not item.ok:
                log.warning("plugin_failed", plugin=item.name, error=item.error)
        return cls(
            store,
            bindings,
            locked,
            loaded,
            connections,
            http=http,
            policy=policy,
            versions=versions,
            accounts=accounts,
        )

    @classmethod
    def when_on(
        cls,
        settings: Settings,
        store: ModuleStore,
        bindings: PluginBindings,
        connections: ConnectionStore | None = None,
        *,
        http: httpx.AsyncClient | None = None,
        policy: EgressPolicy | None = None,
    ) -> PluginHost | None:
        """The host when the install has any plugin (its plugins folder, a developer's paths, an installed package);
        otherwise none, so no plugin route is mounted and no call reaches a plugin."""
        if not settings.plugins:
            return None
        flags = settings.feature_flags
        return cls.start(
            store,
            bindings,
            settings.plugin_locked,
            settings.plugin_folders,
            connections,
            http=http,
            policy=policy,
            versions=flags.on("plugin_updates"),
            accounts=flags.on("several_accounts"),
        )

    @property
    def plugins(self) -> dict[str, Plugin]:
        return {item.plugin.manifest.id: item.plugin for item in self.loaded if item.plugin is not None}

    def by_module(self, module: Mapping[str, Any]) -> Plugin | None:
        pid = plugin_id_of(module)
        return self.plugins.get(pid) if pid else None

    def title_of(self, module: Mapping[str, Any], operation: str) -> str | None:
        """A plugin tool's title from its manifest, read here because the module row stores no title; None for an
        operation of any other module, or a tool without one."""
        plugin = self.by_module(module)
        if plugin is None:
            return None
        tool = plugin.manifest.tool(operation.removeprefix(f"{plugin.manifest.short}_"))
        return (tool.title or None) if tool else None

    def display_of(self, app_id: str) -> tuple[str, str | None] | None:
        """A plugin app's title and logo from its manifest; None for any other app."""
        pid = plugin_of({"app_id": app_id})
        plugin = self.plugins.get(pid) if pid else None
        return (plugin.manifest.title, plugin.manifest.display.logo) if plugin else None

    def awaits_sign_in(self, module: Mapping[str, Any], conn: Mapping[str, Any]) -> bool:
        """Whether a plugin tool's address waits for its account's sign-in: the endpoint names a setting the token or
        the lookup after sign-in fills (Salesforce's instance), and the account holds none yet. Until then the
        account's address is the sign-in host, where its credentials go, not where its tools run."""
        plugin = self.by_module(module)
        if plugin is None:
            return False
        c = plugin.manifest.connection
        filled = set(c.from_token) | ({c.after_sign_in.setting} if c.after_sign_in else set[str]())
        held = dict(conn.get("plugin_settings") or {})
        return any(n in filled and held.get(n) in (None, "") for n in PLACE.findall(plugin.manifest.endpoint))

    async def ensure(self, tenant_id: str, at: datetime) -> None:
        """Writes each loaded plugin's module for the tenant once per process; a second process finds it written."""
        if tenant_id in self._written:
            return
        for plugin in self.plugins.values():
            await self.store.insert_if_missing(module_of(plugin, tenant_id=tenant_id, at=at))
            if self.versions:
                await self._stamp(tenant_id, plugin)
                await self._follow(tenant_id, plugin)
        self._written.add(tenant_id)

    async def take_installed(self, tenant_id: str, team_id: str, plugin: Plugin) -> bool:
        """Records the installed version as the team's (c-609): at a team's first turn-on, and when it takes an
        update. False when the team has no binding."""
        decl = declarations(plugin.manifest)
        return await self.bindings.take(
            tenant_id, team_id, plugin.manifest.id, version=plugin.manifest.version, digest=digest(decl),
            declarations=decl,
        )  # fmt: skip

    async def _stamp(self, tenant_id: str, plugin: Plugin) -> None:
        """Gives every binding of the plugin with no version the installed one, before the row follows the package,
        so from now on an upgrade waits for each team (bindings from before plugin_updates)."""
        for b in await self.bindings.of_plugin(tenant_id, plugin.manifest.id):
            if not b.get("version"):
                await self.take_installed(tenant_id, str(b["team_id"]), plugin)

    async def _follow(self, tenant_id: str, plugin: Plugin) -> None:
        """Rewrites the account's module row when its operations differ from the installed manifest's, under its
        revision; a stale write means another process wrote it first."""
        m = plugin.manifest
        row = await self.store.get(tenant_id, module_id_of(m))
        if row is None:
            return
        kept = [
            t
            for b in await self.bindings.of_plugin(tenant_id, m.id)
            if b.get("declarations")
            for t in tools_of(cast(dict[str, Any], b["declarations"])).values()
        ]
        ops = following(m, cast(list[dict[str, Any]], row["operations"]), kept)
        stored = {str(o["id"]): o for o in row["operations"]}
        same = len(ops) == len(stored) and all(
            o["id"] in stored and all(stored[o["id"]].get(k) == v for k, v in o.items()) for o in ops
        )
        if same:
            return
        try:
            await self.store.put(
                {**row, "operations": ops, "version": m.version}, expected_revision=int(row["revision"]), seeded=False
            )
        except StaleModuleError:
            return

    def tool_for(self, module: Mapping[str, Any], plugin: Plugin, name: str) -> Tool | None:
        """The tool as this call runs it: the team's version's when the call carries one (c-609), else the installed
        manifest's. A Python tool's function is the installed package's either way."""
        tools = cast(dict[str, Tool] | None, module.get("plugin_tools"))
        return tools.get(name) if tools is not None else plugin.manifest.tool(name)

    async def own_settings(self, tenant_id: str, connection_id: str | None) -> dict[str, Any]:
        """The account's own plugin settings (c-580): its sign-in address, the instance its token named."""
        if self.connections is None or not connection_id:
            return {}
        conn = await self.connections.get(tenant_id, connection_id)
        return dict((conn or {}).get("plugin_settings") or {})

    def settings(
        self, plugin: Plugin, team_settings: Mapping[str, Any], own_values: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """The four layers merged: the manifest's defaults, the team's settings, the account's own, then the platform
        admin's locked values over all, so a locked field reads the same in every team whatever the team saved. The
        settings the sign-in addresses use and those read from the token are the account's own (c-580), `own_values`:
        a sandbox signs in at its own address and reaches its own instance."""
        m = plugin.manifest
        own = per_account(m)
        merged: dict[str, Any] = {k: s.default for k, s in m.settings.items() if s.default is not None}
        merged |= {k: v for k, v in team_settings.items() if k in m.settings and k not in own}
        merged |= {k: v for k, v in (own_values or {}).items() if k in own}
        merged |= self.locked_settings(m.id)
        return merged

    async def account_settings(self, tenant_id: str, connection_id: str) -> dict[str, Any]:
        """The plugin's settings on an app's account, merged as a call there reads them, as a person may read them
        (`readable`): what the account's Settings shows and edits. Empty for an account no plugin serves."""
        b = await self.binding_of(tenant_id, connection_id)
        plugin = self.plugins.get(str(b["plugin_id"])) if b else None
        if b is None or plugin is None:
            return {}
        own = await self.own_settings(tenant_id, connection_id)
        plain, secrets = readable(plugin.manifest, self.settings(plugin, dict(b.get("settings") or {}), own))
        return {"pluginSettings": plain, "pluginSecrets": secrets}

    async def connection_hosts(self, tenant_id: str, connection_id: str) -> list[str]:
        """The hosts the plugin serving an account declares, rendered with the account's settings: what its sign-in,
        token and test requests reach without the tenant listing them. None for an account no plugin serves."""
        b = await self.binding_of(tenant_id, connection_id)
        plugin = self.plugins.get(str(b["plugin_id"])) if b else None
        if b is None or plugin is None:
            return []
        own = await self.own_settings(tenant_id, connection_id)
        return hosts_of(plugin.manifest, self.settings(plugin, dict(b.get("settings") or {}), own))

    def installed_digest(self, plugin: Plugin) -> str:
        """The installed version's digest, which a team's binding is compared with for an update (c-609)."""
        return digest(declarations(plugin.manifest))

    def locked_settings(self, plugin_id: str) -> dict[str, Any]:
        """The settings the install fixes for every team of the plugin; a team's own value never replaces one."""
        return dict(self.locked.get(plugin_id) or {})

    async def off_reason(self, tenant_id: str, team_id: str | None, plugin: Plugin) -> str | None:
        """Why the installed plugin is off for the team, or None when the team turned it on: the one place that
        decides whether a plugin's tools run, list and template for a team."""
        if team_id is None:
            return f"{plugin.manifest.title} is turned on per team; this call names no team."
        b = await self.bindings.get(tenant_id, team_id, plugin.manifest.id)
        if b is None or not b["enabled"]:
            return f"{plugin.manifest.title} is off for this team; a team admin turns it on."
        return None

    async def visible(self, tenant_id: str, team_id: str | None, module: Mapping[str, Any]) -> bool:
        """Whether the team sees the module in its tool lists: every other module yes, a plugin's only while on."""
        plugin = self.by_module(module)
        if plugin_id_of(module) is None:
            return True
        return plugin is not None and await self.off_reason(tenant_id, team_id, plugin) is None

    async def team_connection(self, tenant_id: str, team_id: str, module: Mapping[str, Any]) -> str | None:
        """The connection a plugin's module signs in through for this team: its binding's default account (c-616). The
        module row is shared by every team that turned the plugin on, so it holds no connection of its own."""
        plugin = self.by_module(module)
        if plugin is None:
            return None
        b = await self.bindings.get(tenant_id, team_id, plugin.manifest.id)
        return str(b["connection_id"]) if b and b.get("connection_id") else None

    async def binding_of(self, tenant_id: str, connection_id: str) -> dict[str, Any] | None:
        """The binding a connection serves: the one naming it (the default account), else, for another account of the
        app (c-608), the binding of the account's plugin in the account's team."""
        b = await self.bindings.by_connection(tenant_id, connection_id)
        if b is not None or self.connections is None:
            return b
        conn = await self.connections.get(tenant_id, connection_id)
        pid = plugin_of(conn) if conn else None
        if conn is None or pid is None:
            return None
        return await self.bindings.get(tenant_id, str(conn["team_id"]), pid)

    async def account_named(self, tenant_id: str, team_id: str, plugin: Plugin, name: str) -> dict[str, Any] | None:
        """The team's account of the app with this name (c-608), within the team only; None when there is none."""
        if self.connections is None:
            return None
        wanted = name.strip().casefold()
        found = await self.connections.accounts(tenant_id, team_id, plugin_app(plugin.manifest.id))
        return next((a for a in found if str(a.get("account_name") or "").casefold() == wanted), None)

    async def person_default(self, tenant_id: str, team_id: str, plugin: Plugin, person: str) -> str | None:
        """A person's default live account of the app (c-608): their pinned sign-in, else their newest one the system
        has not refused, among the app's accounts that are not a sandbox; None when they hold none."""
        if self.connections is None:
            return None
        found = await self.connections.accounts(tenant_id, team_id, plugin_app(plugin.manifest.id))
        ids = [str(a["id"]) for a in found if not a.get("sandbox")]
        mine = [t for t in await self.connections.own_sign_ins(tenant_id, person, ids) if t["refused_at"] is None]
        pick = next((t for t in mine if t["pinned"]), None) or (mine[0] if mine else None)
        return str(pick["connection_id"]) if pick is not None else None

    async def for_call(
        self,
        tenant_id: str,
        team_id: str | None,
        module: Aggregate,
        run: str,
        *,
        account: str | None = None,
        person: str | None = None,
    ) -> Aggregate:
        """The module as this team's call made in `run` (test or production) sees it: the account it signs in with
        (`connection_id`, from records.account_for, and whether it is a `sandbox`), the endpoint and egress hosts
        rendered with that account's settings, and the merged settings for the transform and a Python tool. A plugin
        that is off for the team, or not loaded, is marked so the gateway refuses the call before anything else."""
        plugin = self.by_module(module)
        if plugin is None:
            return {
                **module,
                "plugin_off": f"{module['display_name']} is no longer installed, so its tools are off. An admin "
                "installs it again to turn them back on.",
            }
        reason = await self.off_reason(tenant_id, team_id, plugin)
        if reason is not None or team_id is None:
            return {**module, "plugin_off": reason or "No team.", "connection_id": None, "egress_hosts": []}
        b: dict[str, Any] = await self.bindings.get(tenant_id, team_id, plugin.manifest.id) or {}
        if account:
            # A call naming an account (c-608) uses that account of the team's, never another team's; an unknown name
            # is refused rather than falling back to the default, so a step never acts in the wrong org.
            named = await self.account_named(tenant_id, team_id, plugin, account) if self.accounts else None
            if named is None:
                why = (
                    f"{plugin.manifest.title} has no account named {account} in this team."
                    if self.accounts
                    else "This install keeps one account per app; a call cannot name one."
                )
                return {**module, "account_missing": why, "connection_id": None, "egress_hosts": []}
            b = {**b, "connection_id": named["id"]}
        else:
            if person and self.accounts:
                # A call naming no account, for a person signed in to several (c-608): the one they pinned, else their
                # newest live sign-in; with none of their own, the team's default.
                chosen = await self.person_default(tenant_id, team_id, plugin, person)
                if chosen is not None:
                    b = {**b, "connection_id": chosen}
            if self.connections is not None:
                # A test run takes the app's sandbox account when the team has one (records.account_for).
                found = await self.connections.accounts(tenant_id, team_id, plugin_app(plugin.manifest.id))
                default = next((a for a in found if str(a["id"]) == str(b.get("connection_id") or "")), None)
                picked = account_for(default, found, run)
                b = {**b, "connection_id": picked["id"] if picked else b.get("connection_id")}
        # The team's own plugin version (c-609), attached before the instance and header checks, so a team that is on
        # but not yet signed in still lists its own version's tools.
        team: dict[str, Any] = {}
        if self.versions and b.get("declarations"):
            decl = cast(dict[str, Any], b["declarations"])
            team = {"plugin_tools": tools_of(decl), "plugin_headers": declared_headers(decl)}
        module = {**module, **team}
        # The account the call signs in with picks the instance and hosts (c-580), so a call never mixes one account's
        # sign-in with another's address.
        conn = (
            await self.connections.get(tenant_id, str(b["connection_id"]))
            if self.connections and b.get("connection_id")
            else None
        )
        module = {**module, "sandbox": bool((conn or {}).get("sandbox"))}
        own = dict((conn or {}).get("plugin_settings") or {})
        settings = self.settings(plugin, dict(b.get("settings") or {}), own)
        endpoint = render(plugin.manifest.endpoint, settings)
        hosts = hosts_of(plugin.manifest, settings)
        tools = cast(dict[str, Tool], team.get("plugin_tools") or {t.name: t for t in plugin.manifest.tools})
        named = header_settings(
            cast(dict[str, str], team.get("plugin_headers", plugin.manifest.headers)), tools.values()
        )
        unsendable = sorted(n for n in named if UNSENDABLE.search(str(settings.get(n) or "")))
        if unsendable:
            return {
                **module,
                "plugin_off": f"{plugin.manifest.title}'s setting {', '.join(unsendable)} holds {{{{ or a line break, "
                "which a header cannot carry; a team admin changes it.",
                "connection_id": None,
                "egress_hosts": [],
            }
        if endpoint is None:
            # No instance yet is not the plugin being off (c-616). On an app each person signs in to, the team
            # account is not required first: this person signs in to the account.
            connection_id = b.get("connection_id")
            sign_in = str((conn or {}).get("sign_in") or "team")
            if sign_in != "team":
                return {
                    **module,
                    "team_id": team_id,
                    "connection_id": connection_id,
                    "egress_hosts": [],
                    "plugin_settings": settings,
                    "plugin_team": team_id,
                    "sign_in_needed": (
                        f"{(conn or {}).get('name') or plugin.manifest.title} has no instance yet. "
                        "Sign in with your own account first."
                    ),
                }
            return {
                **module,
                "instance_missing": (
                    f"{(conn or {}).get('name') or plugin.manifest.title} has no instance yet; a team admin signs in "
                    "to it first."
                ),
                "connection_id": None,
                "egress_hosts": [],
            }
        return {
            **module,
            # For this call the module is the calling team's: its connection is the team's (the sign-in check reads
            # the module's team), and a held write is decided in the team, as for any workspace-level module.
            "team_id": team_id,
            "connection_id": b.get("connection_id"),
            "endpoint": endpoint,
            "egress_hosts": hosts,
            "plugin_settings": settings,
            "plugin_team": team_id,
        }

    async def _look_up(
        self, tenant_id: str, m: Manifest, lookup: AfterSignIn, settings: Mapping[str, Any], token: str
    ) -> str:
        """One GET with the token just issued, to an https address on one of the plugin's egress hosts, through the
        tenant's egress policy, following no redirect; the value at `lookup.read`, checked as `from_token` checks an
        address, or as a plain id. Any failure refuses the sign-in."""
        if lookup.url.startswith("/"):
            base = urlsplit(render(m.connection.token_url or "", settings) or "")
            path = render(lookup.url, settings)
            url = f"{base.scheme}://{base.netloc}{path}" if base.netloc and path else None
        else:
            url = render(lookup.url, settings)
        if url is None:
            raise SignInRefused(f"{m.title}'s lookup after sign-in needs settings that are not set", "lookup_failed")
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in hosts_of(m, settings):
            raise SignInRefused(f"{m.title}'s lookup after sign-in may reach only its own https hosts", "lookup_failed")
        if self.http is None or self.policy is None:
            raise SignInRefused(
                "This service has no egress client, so it runs no lookup after sign-in.", "lookup_failed"
            )
        try:
            own = hosts_of(m, settings)
            await self.policy.check_url(tenant_id, url, own)
            r = await self.http.get(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=LOOKUP_TIMEOUT_S,
                follow_redirects=False,
                extensions=for_tenant(tenant_id, hosts=own),
            )
        except EgressDenied as e:
            raise SignInRefused(f"{m.title}'s lookup after sign-in: {e}", "lookup_failed") from e
        except httpx.HTTPError as e:
            raise SignInRefused(
                f"{m.title}'s lookup after sign-in did not answer ({type(e).__name__})", "lookup_failed"
            ) from e
        if r.status_code != 200:
            raise SignInRefused(f"{m.title}'s lookup after sign-in answered {r.status_code}", "lookup_failed")
        try:
            found = at(r.json(), lookup.read)
        except ValueError:
            found = None
        if isinstance(found, bool) or not isinstance(found, (str, int)) or found == "":
            raise SignInRefused(f"{m.title}'s lookup after sign-in named no {lookup.setting}", "lookup_failed")
        value = str(found)
        if "://" in value:
            value = value.rstrip("/")
            host = urlsplit(value).hostname or ""
            if not value.startswith("https://") or not any(host.endswith(s) for s in m.connection.token_hosts):
                raise SignInRefused(
                    f"the lookup after sign-in named {host or 'no host'} as its {lookup.setting}; {m.title} takes "
                    f"only a host under {', '.join(m.connection.token_hosts)}",
                    "token_host",
                )
        elif not PLAIN_VALUE.match(value):
            raise SignInRefused(
                f"the lookup after sign-in named a {lookup.setting} {m.title} cannot use in an address", "lookup_failed"
            )
        return value

    def operation(self, module: Mapping[str, Any], op: dict[str, Any]) -> dict[str, Any]:
        """The operation as this call runs it, from the loaded manifest rather than the module row, which is written
        once per tenant and holds no team's settings (c-584): the tool's amount limit, its headers rendered from the
        call's settings, and a form tool's form. Unchanged for a plugin that is off for the call or not loaded."""
        plugin = self.by_module(module)
        tools = cast(dict[str, Tool] | None, module.get("plugin_tools"))
        if plugin is None or (module.get("plugin_off") and tools is None):
            return op
        m = plugin.manifest
        name = str(op["name"]).removeprefix(f"{m.short}_")
        headers: Mapping[str, str] = m.headers
        if tools is not None:
            # The team's version (c-609): the op as that version declared it, under the row's id; a tool it lacks is
            # refused naming the update, and one the installed package dropped is enabled again for this team.
            tool = tools.get(name)
            if tool is None:
                why = (
                    f"{m.title} {m.version} adds this tool; a team admin takes the update first."
                    if m.tool(name) is not None
                    else f"{m.title} no longer has this tool, and this team's version does not either."
                )
                return {**op, "enabled": False, "hidden_reason": why}
            headers = cast(dict[str, str], module.get("plugin_headers") or {})
            op = {**op, **operation_of(m, tool, str(op["id"]))}
        else:
            tool = m.tool(name)
            if tool is None:
                return op
        out = {
            **op,
            "amount_max": tool.amount_max,
            "headers": headers_of(headers, tool, module.get("plugin_settings") or {}),
        }
        if tool.request is not None and tool.request.form is not None:
            # The manifest's `form` is a form body, the one form path a builder's tool takes too (c-616).
            out["body"], out["body_encoding"] = json.dumps(dict(tool.request.form)), "form"
        return out

    async def on_token(
        self,
        tenant_id: str,
        connection_id: str,
        answer: dict[str, Any],
        own: bool = False,
    ) -> dict[str, Any] | None:
        """At sign-in on a plugin's connection: each setting the plugin reads from the token (instance_url) is taken
        from the answer, refused unless it is an https host under the plugin's token hosts; then the lookup after
        sign-in, if the plugin has one, fills its setting (c-584). `own` is a person's own sign-in, which may not
        change what the team's holds (`settle_at_sign_in`). Nothing is saved until every check passes, then all of it
        on the account (c-580). Returns where Test connection reads: the instance and the plugin's health-check
        path."""
        b = await self.binding_of(tenant_id, connection_id)
        plugin = self.plugins.get(str(b["plugin_id"])) if b else None
        if b is None or plugin is None:
            return None
        m = plugin.manifest
        read: dict[str, Any] = {}
        for setting, field_name in m.connection.from_token.items():
            value = str(answer.get(field_name) or "").rstrip("/")
            parts = urlsplit(value)
            host = parts.hostname or ""
            if parts.scheme != "https" or not any(host.endswith(s) for s in m.connection.token_hosts):
                raise SignInRefused(
                    f"the sign-in named {host or 'no host'} as its {setting}; {m.title} takes only a host under "
                    f"{', '.join(m.connection.token_hosts)}",
                    "token_host",
                )
            read[setting] = value
        held = await self.own_settings(tenant_id, connection_id)
        lookup = m.connection.after_sign_in
        if lookup is not None:
            now = self.settings(plugin, dict(b.get("settings") or {}), {**held, **read})
            read[lookup.setting] = await self._look_up(tenant_id, m, lookup, now, str(answer.get("access_token") or ""))
        read = settle_at_sign_in(held, read, own=own)
        # Saved as the signed-in account's own (c-580): a sandbox sign-in leaves the live account's instance as it was.
        if read and self.connections is not None:
            await self.connections.set_plugin_settings(tenant_id, connection_id, read)
        values = await self.own_settings(tenant_id, connection_id) or {**held, **read}
        merged = self.settings(plugin, dict(b.get("settings") or {}), values)
        endpoint = render(m.endpoint, merged)
        check = m.connection.health_check
        if endpoint is None or check is None:
            return None
        origin = urlsplit(endpoint)
        path = render(check.path, merged)
        return {"baseUrl": f"{origin.scheme}://{origin.netloc}", **({"testPath": path} if path else {})}
