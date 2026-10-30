"""The plugins this tools-service loaded at start, the module each one is, and each call's view of it (c-564).

Each loaded plugin is one workspace-level tool module (no team owns it, c-433) whose operations are its tools, named
`<plugin>_<tool>`, so grants, approval, OPA, the call log and MCP treat them as any tool. The module row holds no
connection, endpoint or egress list: `for_call` fills those from the calling team's binding on every call, so two teams
running the same plugin reach their own Salesforce org with their own sign-in. A plugin is off for a team unless the
platform admin turned it on for the install (the `plugins` policy) and the team turned it on (its binding)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast
from urllib.parse import urlsplit

from ops_plugin_sdk import Manifest, Plugin
from ops_plugin_sdk.loader import Loaded, discover
from ops_plugin_sdk.manifest import InputField, Tool
from ops_service_kit.settings import Settings

from ..modules.seed import blank
from ..store.modules import Aggregate, ModuleStore
from ..store.plugin_bindings import PluginBindings
from .switches import InstallSwitches

TEMPLATE_PREFIX = "plugin:"
PLACE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


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


CURSOR = {
    "name": "cursor",
    "type": "string",
    "required": False,
    "description": "The next_cursor a previous page answered, for the page after it",
}


_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def per_environment(manifest: Manifest) -> set[str]:
    """The settings each environment keeps its own (c-580): those read from the token (the instance) and those the
    sign-in addresses name (Salesforce's login_url), since a sandbox signs in elsewhere and lands elsewhere."""
    c = manifest.connection
    named = {n for t in (c.authorize_url, c.token_url, c.revoke_url) if t for n in _PLACEHOLDER.findall(t)}
    return (set(c.from_token) | named) & set(manifest.settings)


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


def module_of(plugin: Plugin, *, tenant_id: str, at: datetime) -> Aggregate:
    """The plugin as one published workspace-level module: data tools on the http executor, Python tools on the
    plugin executor. Its endpoint is the manifest's template; a call renders it with the team's settings."""
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
    ops: list[dict[str, Any]] = []
    for i, t in enumerate(m.tools):
        ops.append(
            {
                "id": f"{module_id_of(m)}_op{i + 1}",
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
                "amount_max": None,
                "needs_person": t.needs_person,
                "scopes": list(t.scopes),
                "stub": {"ok": True},
            }
        )
    version = {**mod["versions"][0], "id": f"{module_id_of(m)}_v{m.version}", "version": m.version, "major": 1}
    version.update(status="published", published_at=at, note=f"{m.title} plugin {m.version}")
    return {
        **mod,
        "status": "published",
        "system": m.title,
        "description": f"The {m.title} plugin's tools ({m.id} {m.version}).",
        "endpoint": m.endpoint,
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
    switches: InstallSwitches
    loaded: list[Loaded] = field(default_factory=list[Loaded])
    _written: set[str] = field(default_factory=set[str])

    @classmethod
    def start(
        cls, store: ModuleStore, bindings: PluginBindings, switches: InstallSwitches, folders: Sequence[str] = ()
    ) -> PluginHost:
        """Reads every installed plugin once, at start, and the developer's plugin folders; a failed one is kept with
        its error for /v1/plugins."""
        return cls(store, bindings, switches, discover(folders=folders))

    @classmethod
    def when_on(
        cls, settings: Settings, store: ModuleStore, bindings: PluginBindings, switches: InstallSwitches
    ) -> PluginHost | None:
        """The host when plugins are switched on (OPS_PLUGINS); otherwise none, so no plugin is read, no plugin route
        is mounted and no call reaches a plugin."""
        return cls.start(store, bindings, switches, settings.plugin_paths) if settings.plugins else None

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

    async def ensure(self, tenant_id: str, at: datetime) -> None:
        """Writes each loaded plugin's module for the tenant once per process; a second process finds it written."""
        if tenant_id in self._written:
            return
        for plugin in self.plugins.values():
            await self.store.insert_if_missing(module_of(plugin, tenant_id=tenant_id, at=at))
        self._written.add(tenant_id)

    async def settings(
        self, tenant_id: str, plugin: Plugin, team_settings: Mapping[str, Any], environment: str = "production"
    ) -> dict[str, Any]:
        """The four layers merged: the manifest's defaults, the team's settings, then the platform admin's locked
        values over both, so a locked field reads the same in every team whatever the team saved. The settings the
        sign-in addresses use and those read from the token are the environment's own (c-580), kept under
        `environments` in the team's settings: a sandbox signs in at its own address and reaches its own instance,
        and a test call never falls back to production's. A binding from before reads its top-level values as
        production's."""
        m = plugin.manifest
        own = per_environment(m)
        merged: dict[str, Any] = {k: s.default for k, s in m.settings.items() if s.default is not None}
        shared = environment == "production"
        merged |= {k: v for k, v in team_settings.items() if k in m.settings and (k not in own or shared)}
        envs = cast(dict[str, dict[str, Any]], team_settings.get("environments") or {})
        merged |= {k: v for k, v in (envs.get(environment) or {}).items() if k in own}
        merged |= await self.switches.locked(tenant_id, m.id)
        return merged

    async def off_reason(self, tenant_id: str, team_id: str | None, plugin: Plugin) -> str | None:
        """Why the plugin is off for the team, or None when both switches are on."""
        if not await self.switches.on(tenant_id, plugin.manifest.id):
            return f"{plugin.manifest.title} is off for this install; the platform admin turns it on."
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

    async def for_call(
        self, tenant_id: str, team_id: str | None, module: Aggregate, environment: str = "production"
    ) -> Aggregate:
        """The module as this team's call sees it: the team's connection, the endpoint and egress hosts rendered with
        the team's settings, and the merged settings for the transform and a Python tool. A plugin that is off for
        the team, or not loaded, is marked so the gateway refuses the call before anything else."""
        plugin = self.by_module(module)
        if plugin is None:
            return {**module, "plugin_off": f"{module['display_name']} is not installed on this service."}
        reason = await self.off_reason(tenant_id, team_id, plugin)
        if reason is not None or team_id is None:
            return {**module, "plugin_off": reason or "No team.", "connection_id": None, "egress_hosts": []}
        b = await self.bindings.get(tenant_id, team_id, plugin.manifest.id) or {}
        # The call's environment picks the instance and hosts (c-580), so a test call cannot reach production's.
        settings = await self.settings(tenant_id, plugin, dict(b.get("settings") or {}), environment)
        endpoint = render(plugin.manifest.endpoint, settings)
        hosts = [urlsplit(h).hostname or h for h in (render(e, settings) for e in plugin.manifest.egress) if h]
        if endpoint is None:
            return {
                **module,
                "plugin_off": f"{plugin.manifest.title} has no instance yet; the team admin signs in first.",
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

    async def on_token(
        self, tenant_id: str, connection_id: str, answer: dict[str, Any], environment: str = "production"
    ) -> dict[str, Any] | None:
        """At sign-in on a plugin's connection: each setting the plugin reads from the token (instance_url) is taken
        from the answer, refused unless it is an https host under the plugin's token hosts, and saved on the team's
        binding. Returns where Test connection reads: the instance and the plugin's health-check path."""
        b = await self.bindings.by_connection(tenant_id, connection_id)
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
                raise ValueError(
                    f"the sign-in named {host or 'no host'} as its {setting}; {m.title} takes only a host under "
                    f"{', '.join(m.connection.token_hosts)}"
                )
            read[setting] = value
        # Saved as the signed-in environment's own (c-580): a sandbox sign-in leaves production's instance as it was.
        saved = dict(b.get("settings") or {})
        envs = cast(dict[str, dict[str, Any]], dict(saved.get("environments") or {}))
        envs[environment] = {**(envs.get(environment) or {}), **read}
        # Production's also stay at the top level, where a binding from before kept them.
        settings = {**saved, **(read if environment == "production" else {}), "environments": envs}
        await self.bindings.put(
            tenant_id,
            str(b["team_id"]),
            m.id,
            enabled=bool(b["enabled"]),
            connection_id=connection_id,
            settings=settings,
            by="sign-in",
        )
        merged = await self.settings(tenant_id, plugin, settings, environment)
        endpoint = render(m.endpoint, merged)
        check = m.connection.health_check
        if endpoint is None or check is None:
            return None
        origin = urlsplit(endpoint)
        path = render(check.path, merged)
        return {"baseUrl": f"{origin.scheme}://{origin.netloc}", **({"testPath": path} if path else {})}
