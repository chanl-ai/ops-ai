"""The plugins this tools-service loaded at start, the module each one is, and each call's view of it.

Each loaded plugin is one workspace-level tool module (no team owns it) whose operations are its tools, named
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
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

import httpx

from ops_access import tool_waits
from ops_plugin_sdk import Manifest, Plugin
from ops_plugin_sdk.answers import error_rule
from ops_plugin_sdk.loader import Loaded, discover
from ops_plugin_sdk.manifest import AfterSignIn, InputField, Other, Setting, SignInError, Tool
from ops_plugin_sdk.paging import at
from ops_plugin_sdk.paging import headers as request_headers
from ops_plugin_sdk.versions import declarations, digest, tools_of
from ops_plugin_sdk.versions import headers_of as declared_headers
from ops_service_kit.logging import get_logger
from ops_service_kit.settings import Settings

from ..auth.tokens import SIGNED_IN_AS, person_named
from ..connections.records import account_for, choice_needed, default_sign_in
from ..egress import EgressDenied, EgressPolicy, for_tenant
from ..environments import LIVE
from ..modules.seed import blank
from ..store.connections import PERSON_ORIGIN, ConnectionStore, name_key, plugin_app, plugin_of
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
# A host a person types in place of a choice: lower-case labels of letters, digits and inner hyphens, two or more, so
# no port, path, user or second address rides in with it.
HOSTNAME = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


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


def typed_host(other: Other, value: object) -> str | None:
    """The host a value was made from by `other.value` (`https://{host}/services/oauth2`), when it ends in one of
    `other.hosts` with a label of its own before the suffix; None for any other value."""
    if not isinstance(value, str):
        return None
    before, _, after = other.value.partition("{host}")
    if len(value) <= len(before) + len(after) or not (value.startswith(before) and value.endswith(after)):
        return None
    host = value[len(before) : len(value) - len(after)].lower()
    if not HOSTNAME.match(host):
        return None
    return host if any(host.endswith(s.lower()) and len(host) > len(s) for s in other.hosts) else None


def filled_at_sign_in(manifest: Manifest) -> set[str]:
    """The settings the sign-in fills: those read from the token, and the lookup after sign-in's."""
    c = manifest.connection
    return set(c.from_token) | ({c.after_sign_in.setting} if c.after_sign_in else set[str]())


def shown_value(setting: Setting, value: object) -> str:
    """A setting's value as a person reads it: its choice's label, the company host typed for it, or an address's
    host."""
    choice = next((c for c in setting.choices or [] if c.value == value), None)
    if choice is not None:
        return choice.label
    typed = typed_host(setting.other, value) if setting.other is not None else None
    if typed is not None:
        return typed
    text = str(value)
    return (urlsplit(text).hostname or text) if "://" in text else text


def sign_in_values(manifest: Manifest, held: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Where an account signs in (`place`: a setting each account keeps with choices or a typed host, such as
    Salesforce's sign-in address) and what its sign-in found (`found`: its org's address), from the account's settings
    `held`, in the manifest's order. A secret is never among them."""
    found = filled_at_sign_in(manifest)
    own = per_account(manifest)
    out: list[dict[str, Any]] = []
    for k, s in manifest.settings.items():
        value = held.get(k)
        if s.secret or value in (None, ""):
            continue
        kind = "found" if k in found else "place" if k in own and (s.choices or s.other) else None
        if kind is not None:
            out.append(
                {"name": k, "label": s.title or k, "kind": kind, "value": str(value), "shown": shown_value(s, value)}
            )
    return out


SIGNED_IN = "Signed in as"


def _entry(label: str, value: object, shown: str) -> dict[str, str]:
    return {"label": label, "value": str(value), "shown": shown}


def account_identity(
    manifest: Manifest | None, held: Mapping[str, Any], signed_in_as: str | None, base: str = ""
) -> list[dict[str, str]]:
    """What tells one account of an app from its others, shown under its name on every screen: the settings the
    plugin's `connection.identity` names, in its order; with none declared, what the sign-in filled, then where the
    account signs in (its sign-in address, as its host); a custom app's address host (`base`); and last who signed in.
    Built on sign_in_values, so the place and the found value have one source. A secret is never among them."""
    out: list[dict[str, str]] = []
    if manifest is not None:
        own = per_account(manifest)
        # A per-account address left at the plugin's default (GitHub's github.com) still tells the account apart.
        given = {k: s.default for k, s in manifest.settings.items() if k in own and s.default not in (None, "")}
        values = {**given, **{k: v for k, v in held.items() if v not in (None, "")}}
        if manifest.connection.identity:
            for name in manifest.connection.identity:
                setting = manifest.settings.get(name)
                if setting is not None and not setting.secret and values.get(name) not in (None, ""):
                    value = values[name]
                    out.append(_entry(setting.title or name, value, shown_value(setting, value)))
        else:
            listed = sign_in_values(manifest, values)
            out += [{k: v[k] for k in ("label", "value", "shown")} for v in listed if v["kind"] == "found"]
            out += [{k: v[k] for k in ("label", "value", "shown")} for v in listed if v["kind"] == "place"]
            if not out:
                for name in sorted(own):
                    setting, value = manifest.settings[name], values.get(name)
                    if not setting.secret and isinstance(value, str) and "://" in value:
                        out.append(_entry(setting.title or name, value, shown_value(setting, value)))
    elif base:
        out.append({"label": "Address", "value": base, "shown": urlsplit(base).hostname or base})
    if signed_in_as:
        out.append({"label": SIGNED_IN, "value": signed_in_as, "shown": signed_in_as})
    seen: set[str] = set()
    return [e for e in out if not (e["shown"] in seen or seen.add(e["shown"]))]


def same_place(identity: Sequence[Mapping[str, str]]) -> tuple[str, ...]:
    """The part of an identity that says where an account points (who signed in left out): two accounts with the same
    non-empty one point at the same org."""
    return tuple(e["shown"] for e in identity if e["label"] != SIGNED_IN)


def points_at(identity: Sequence[Mapping[str, str]]) -> str | None:
    """Where an account points, as shown, with who signed in left out; None when it names no place. Text a model reads
    uses this, never the identity, so a person's email stays out of it."""
    place = same_place(identity)
    return place[0] if place else None


def offered(setting: Setting, value: object) -> bool:
    """Whether a team's value is one the setting offers: one of its choices, or a host typed for its `other`. A setting
    that declares neither takes any value."""
    if not setting.choices and setting.other is None:
        return True
    same = [
        c for c in setting.choices or [] if c.value == value and isinstance(c.value, bool) == isinstance(value, bool)
    ]
    return bool(same) or (setting.other is not None and typed_host(setting.other, value) is not None)


def missing_objects(conn: Mapping[str, Any] | None, package_id: str) -> list[str]:
    """The objects of a package app that the account's last Test found missing (`health.packages`). Empty when the
    package is installed there, and when the account was never checked for it: an account signed in before the
    package was installed keeps working until its next Test says otherwise."""
    health = cast(dict[str, Any], (conn or {}).get("health") or {})
    packages = cast(dict[str, Any], health.get("packages") or {})
    missing = cast(list[Any], cast(dict[str, Any], packages.get(package_id) or {}).get("missing") or [])
    return [str(n) for n in missing]


def own_and_registration(conn: Mapping[str, Any] | None) -> dict[str, Any]:
    """An account's own plugin settings with its app credential's over them (store.connections joins those in as
    `credential_settings`): what PluginHost.settings takes as the account's layer."""
    held = {k: v for k, v in dict((conn or {}).get("credential_settings") or {}).items() if v not in (None, "")}
    return {**dict((conn or {}).get("plugin_settings") or {}), **held}


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
    rendered from the call's settings. A header whose setting is unset is left out. The kit's own rule, so `opsai plugin
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
    """The settings each account keeps its own: those read from the token (the instance) and those the sign-in
    addresses name, since a test account signs in elsewhere and lands elsewhere. A setting `asked: config` (Salesforce's
    login_url) is among them: its auth config's value wins when the config sets one, and an account on a config that
    leaves it unset (Ops AI's app always does) gives its own."""
    c = manifest.connection
    named = {n for t in (c.authorize_url, c.token_url, c.revoke_url) if t for n in _PLACEHOLDER.findall(t)}
    looked = {c.after_sign_in.setting} if c.after_sign_in else set[str]()
    configs = {k for k, s in manifest.settings.items() if s.asked == "config"}
    return (set(c.from_token) | named | looked | configs) & set(manifest.settings)


def fixed_fields(manifest: Manifest) -> list[str]:
    """The sign-in kinds' fields the plugin sets itself: how its key is sent, its sign-in, token and revocation
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
    """The token call's and sign-in address's settings the plugin fixes: how its client is sent, and its extra
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


def tools_added(m: Manifest, binding: Mapping[str, Any] | None) -> set[str] | None:
    """The operations the team added, by operation name; None while the binding keeps every tool added (one made
    before the catalog, or no binding). Stored as the binding's `tools_on`, by tool name."""
    held = (binding or {}).get("tools_on")
    return None if held is None else {m.operation(str(t)) for t in cast(list[Any], held)}


def first_tools_on(m: Manifest) -> list[str]:
    """What a new app starts with: every tool on, its writes included, so a person who connects it can write at once.
    The app's "Ask before changes" switch (appsChangeWithoutAsking) keeps the person in chat asked before each write;
    a binding made earlier keeps the list it holds."""
    return sorted(t.name for t in m.tools)


def tools_added_view(m: Manifest, binding: Mapping[str, Any] | None) -> dict[str, Any]:
    """What a call needs to refuse a tool the team has not added, in plain words: the operations added and their
    titles."""
    on = tools_added(m, binding)
    if on is None:
        return {}
    return {
        "tools_on": sorted(on),
        "app_title": m.title,
        "tool_titles": {m.operation(t.name): t.title or t.name for t in m.tools},
    }


def operation_of(m: Manifest, t: Tool, op_id: str) -> dict[str, Any]:
    """One tool as a module operation: on the http executor for a plain data tool, on the plugin executor for one that
    pages, checks its inputs or is Python. Built for the module row and, per call, from the team's version."""
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
        "requires_approval": tool_waits(t.access),
        # The manifest's ask-first flag is the tool's default answer, a reviewer's approval; left out, the app and the
        # team decide.
        "approval_mode": "reviewer" if t.access == "write" and t.requires_approval is True else None,
        "approvers": 1,
        "amount_max": t.amount_max,
        "needs_person": t.needs_person,
        "scopes": list(t.scopes),
        "output_shape": t.shape,
        "stub": {"ok": True},
    }


def following(m: Manifest, row_ops: Sequence[Mapping[str, Any]], kept: Iterable[Tool] = ()) -> list[dict[str, Any]]:
    """The module row's operations for the installed manifest: each tool keeps the id of the row's operation
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
    # Where each account's own plugin settings are kept: on the account itself.
    connections: ConnectionStore | None = None
    # The egress client and policy the lookup after sign-in goes through, as any call does.
    http: httpx.AsyncClient | None = None
    policy: EgressPolicy | None = None
    # The plugin_updates flag: each team runs the plugin version it took. Off, the row is written once and
    # every call reads the installed manifest, as before.
    versions: bool = False
    # The plugins Ops AI ships built in: on for a team that never set its switch, so a new team's templates both list
    # and run; a team admin turning one off writes a binding that keeps it off.
    builtin: frozenset[str] = frozenset()
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
        builtin_dir: Path | None = None,
    ) -> PluginHost:
        """Reads every installed plugin once, at start, and the developer's plugin folders; a failed one is left out and
        logged with why, where the install's admin reads it."""
        loaded = discover(folders=folders)
        for item in loaded:
            if not item.ok:
                log.warning("plugin_failed", plugin=item.name, error=item.error)
        inside = builtin_dir.resolve() if builtin_dir else None
        builtin = frozenset(
            i.plugin.manifest.id
            for i in loaded
            if i.plugin is not None and inside is not None and i.plugin.root.resolve().is_relative_to(inside)
        )
        return cls(
            store,
            bindings,
            locked,
            loaded,
            connections,
            http=http,
            policy=policy,
            versions=versions,
            builtin=builtin,
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
            builtin_dir=settings.builtin_plugins_dir,
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
        """Records the installed version as the team's: at a team's first turn-on, and when it takes an
        update. False when the team has no binding."""
        decl = declarations(plugin.manifest, plugin.root)
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
        """The tool as this call runs it: the team's version's when the call carries one, else the installed
        manifest's. A Python tool's function is the installed package's either way."""
        tools = cast(dict[str, Tool] | None, module.get("plugin_tools"))
        return tools.get(name) if tools is not None else plugin.manifest.tool(name)

    async def own_settings(self, tenant_id: str, connection_id: str | None) -> dict[str, Any]:
        """The account's own plugin settings (its sign-in address, the instance its token named) and the settings of
        the app credential it signs in with (its registration's), the credential's winning."""
        if self.connections is None or not connection_id:
            return {}
        conn = await self.connections.get(tenant_id, connection_id)
        return own_and_registration(conn)

    def settings(
        self, plugin: Plugin, team_settings: Mapping[str, Any], own_values: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """The four layers merged: the manifest's defaults, the team's settings, the account's own, then the platform
        admin's locked values over all, so a locked field reads the same in every team whatever the team saved. The
        settings the sign-in addresses use and those read from the token are the account's own, `own_values`:
        a sandbox signs in at its own address and reaches its own instance."""
        m = plugin.manifest
        own = per_account(m)
        merged: dict[str, Any] = {k: s.default for k, s in m.settings.items() if s.default is not None}
        merged |= {k: v for k, v in team_settings.items() if k in m.settings and k not in own}
        # The account's own, and the registration's its app credential holds (own_and_registration).
        mine = own | set(m.config_settings)
        merged |= {k: v for k, v in (own_values or {}).items() if k in mine}
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

    async def sign_in_error(
        self, tenant_id: str, connection_id: str, error: str, description: str | None
    ) -> SignInError | None:
        """What the plugin serving an account says of a refused sign-in: its first sign_in_errors entry for the code
        and description; None for an account no plugin serves, or a code the plugin does not name."""
        b = await self.binding_of(tenant_id, connection_id)
        plugin = self.plugins.get(str(b["plugin_id"])) if b else None
        return plugin.manifest.connection.sign_in_error(error, description) if plugin else None

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
        """The installed version's digest, which a team's binding is compared with for an update."""
        return digest(declarations(plugin.manifest, plugin.root))

    def locked_settings(self, plugin_id: str) -> dict[str, Any]:
        """The settings the install fixes for every team of the plugin; a team's own value never replaces one."""
        return dict(self.locked.get(plugin_id) or {})

    async def off_reason(self, tenant_id: str, team_id: str | None, plugin: Plugin) -> str | None:
        """Why the installed plugin is off for the team, or None when it is on (the team turned it on, or it is built in
        and the team never turned it off): the one place that decides whether a plugin's tools run for a team."""
        if team_id is None:
            return f"{plugin.manifest.title} is turned on per team; this call names no team."
        b = await self.bindings.get(tenant_id, team_id, plugin.manifest.id)
        if b is None and plugin.manifest.id in self.builtin:
            return None
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
        """The connection a plugin's module signs in through for this team: its binding's default account. The
        module row is shared by every team that turned the plugin on, so it holds no connection of its own."""
        plugin = self.by_module(module)
        if plugin is None:
            return None
        b = await self.bindings.get(tenant_id, team_id, plugin.manifest.id)
        return str(b["connection_id"]) if b and b.get("connection_id") else None

    async def on_signed_in(self, tenant_id: str, connection_id: str, by: str) -> None:
        """After a finished sign-in on a plugin's account: the app is on for the account's team, with this account its
        default while it has no other, so a connected account is never left behind an app that is off."""
        if self.connections is None:
            return
        conn = await self.connections.get(tenant_id, connection_id)
        pid = plugin_of(conn) if conn else None
        plugin = self.plugins.get(pid) if pid else None
        if conn is None or plugin is None:
            return
        team = str(conn["team_id"])
        b = await self.bindings.get(tenant_id, team, plugin.manifest.id)
        held = b.get("connection_id") if b else None
        if held is not None and await self.connections.get(tenant_id, str(held)) is None:
            held = None
        if b is not None and b.get("enabled") and held is not None:
            return
        await self.bindings.put(
            tenant_id,
            team,
            plugin.manifest.id,
            enabled=True,
            connection_id=str(held or connection_id),
            settings=dict((b or {}).get("settings") or {}),
            by=by,
        )
        if b is None:
            # A new app hands agents every tool, as turning it on does.
            await self.bindings.set_tools(tenant_id, team, plugin.manifest.id, first_tools_on(plugin.manifest))
        if self.versions and not (b or {}).get("version"):
            await self.take_installed(tenant_id, team, plugin)

    async def sign_in_scopes(self, tenant_id: str, connection_id: str) -> list[str] | None:
        """The permissions a plugin account's sign-in asks for: the plugin's required ones and those its team's
        added tools need. None for an account no plugin serves, or an app whose catalog was never changed, which
        keeps asking for what its auth config lists."""
        if self.connections is None:
            return None
        conn = await self.connections.get(tenant_id, connection_id)
        pid = plugin_of(conn) if conn else None
        plugin = self.plugins.get(pid) if pid else None
        if conn is None or plugin is None:
            return None
        m = plugin.manifest
        on = tools_added(m, await self.bindings.get(tenant_id, str(conn["team_id"]), m.id))
        if on is None:
            return None
        needed = [s.id for s in m.connection.scopes if s.required]
        needed += [x for t in m.tools if m.operation(t.name) in on for x in t.scopes]
        return list(dict.fromkeys(needed))

    async def tools_off(self, tenant_id: str, team_id: str) -> set[str]:
        """The operations of the team's apps it has not added, by operation name: what agents are not offered."""
        off: set[str] = set()
        for pid, b in (await self.bindings.of_team(tenant_id, team_id)).items():
            plugin = self.plugins.get(pid)
            on = tools_added(plugin.manifest, b) if plugin is not None else None
            if plugin is not None and on is not None:
                off |= {plugin.manifest.operation(t.name) for t in plugin.manifest.tools} - on
        return off

    async def binding_of(self, tenant_id: str, connection_id: str) -> dict[str, Any] | None:
        """The binding a connection serves: the one naming it (the default account), else, for another account of the
        app, the binding of the account's plugin in the account's team."""
        b = await self.bindings.by_connection(tenant_id, connection_id)
        if b is not None or self.connections is None:
            return b
        conn = await self.connections.get(tenant_id, connection_id)
        pid = plugin_of(conn) if conn else None
        if conn is None or pid is None:
            return None
        return await self.bindings.get(tenant_id, str(conn["team_id"]), pid)

    async def account_named(
        self, tenant_id: str, team_id: str, plugin: Plugin, name: str, *, person: str | None = None
    ) -> dict[str, Any] | None:
        """The team's account of the app with this name, within the team only; None when there is none. A name is
        unique within its owner, so the team's account and a person's own may share it: the caller's own account of
        that name (`person`, their sign-in key) comes first, then the team's, then another person's own, which the
        call is refused for (`_named`)."""
        if self.connections is None:
            return None
        wanted = name_key(name)
        found = await self.connections.accounts(tenant_id, team_id, plugin_app(plugin.manifest.id))
        same = [a for a in found if wanted and name_key(a.get("account_name")) == wanted]
        if person:
            signed = await self.connections.own_sign_ins(tenant_id, person, [str(a["id"]) for a in same])
            ids = {str(t["connection_id"]) for t in signed}
            theirs = next((a for a in same if a.get("origin") == PERSON_ORIGIN and str(a["id"]) in ids), None)
            if theirs is not None:
                return theirs
        return next((a for a in same if a.get("origin") != PERSON_ORIGIN), same[0] if same else None)

    async def person_default(self, tenant_id: str, team_id: str, plugin: Plugin, person: str) -> str | None:
        """A person's default live account of the app: their pinned sign-in, else their newest one the system
        has not refused, among the app's accounts that are not a sandbox; None when they hold none."""
        if self.connections is None:
            return None
        found = await self.connections.accounts(tenant_id, team_id, plugin_app(plugin.manifest.id))
        ids = [str(a["id"]) for a in found if not a.get("sandbox")]
        pick = default_sign_in(await self.connections.own_sign_ins(tenant_id, person, ids))
        return str(pick["connection_id"]) if pick is not None else None

    async def account_choice(self, tenant_id: str, team_id: str, plugin: Plugin, person: str) -> dict[str, Any] | None:
        """What a call must ask the person when they hold two or more live accounts of the app and chose no default:
        the app and each account, named as its sign-in named the person; None when there is nothing to choose."""
        if self.connections is None:
            return None
        found = await self.connections.accounts(tenant_id, team_id, plugin_app(plugin.manifest.id))
        live = {str(a["id"]): a for a in found if not a.get("sandbox")}
        mine = await self.connections.own_sign_ins(tenant_id, person, list(live))
        if not choice_needed(mine):
            return None
        accounts = [
            {
                "connectionId": str(t["connection_id"]),
                "name": str(live[str(t["connection_id"])]["name"]),
                "account": t.get("account"),
                # Where each points (its org, its server), so two accounts signed in as one person read apart.
                "identity": account_identity(
                    plugin.manifest, own_and_registration(live[str(t["connection_id"])]), t.get("account")
                ),
            }
            for t in mine
            if t.get("refused_at") is None
        ]
        return {"app": plugin.manifest.title, "appId": plugin_app(plugin.manifest.id), "accounts": accounts}

    async def _named(
        self, tenant_id: str, team_id: str, plugin: Plugin, name: str, *, run: str, person: str | None
    ) -> dict[str, Any]:
        """The account a call naming `name` signs in with (`id`), or why it is refused (`refused`). The name is one of
        the team's accounts, never another team's (account_named); an unknown name is refused rather than falling back
        to the default, so a call never acts in an org nobody chose. One person's own account signs only that person's
        calls: a call acting for nobody (a schedule, a step) or for anyone else is refused, whoever wrote the name.
        A test run never acts in a named live account: it takes the app's test account (records.account_for), and is
        refused when the team has none."""
        title = plugin.manifest.title
        named = await self.account_named(tenant_id, team_id, plugin, name, person=person)
        if named is None or self.connections is None:
            return {"refused": {"account_missing": f"{title} has no account named {name} in this team."}}
        if named.get("origin") == PERSON_ORIGIN:
            mine = await self.connections.own_sign_ins(tenant_id, person, [str(named["id"])]) if person else []
            if not mine:
                why = f"{title}'s account {name} is one person's own, so only their own calls use it."
                return {"refused": {"account_not_yours": why}}
        if run != LIVE and not named.get("sandbox"):
            found = await self.connections.accounts(tenant_id, team_id, plugin_app(plugin.manifest.id))
            test = account_for(None, found, run)
            if test is None:
                why = f"{title} has no test account, so a test run cannot use {name}, a live one."
                return {"refused": {"sandbox_required": why}}
            return {"id": test["id"]}
        return {"id": named["id"]}

    async def _choose(
        self,
        tenant_id: str,
        team_id: str,
        plugin: Plugin,
        b: dict[str, Any],
        run: str,
        *,
        account: str | None,
        accounts: Mapping[str, str] | None,
        person: str | None,
    ) -> dict[str, Any]:
        """The account a call on `plugin`'s accounts signs in with, as `binding` (the team's binding with that account
        as its connection_id), or what the call is refused or asked instead (`account_missing`, `account_choice`, ...).
        A package app's call passes the app it runs on, so it chooses among that app's accounts only."""
        # The caller sends every app's choice (`accounts`, app id to name); this call reads its own app's entry. The
        # single `account` string older callers send names the account for whichever app the call is for.
        account = (accounts or {}).get(plugin_app(plugin.manifest.id)) or account
        if account:
            refused = await self._named(tenant_id, team_id, plugin, account, run=run, person=person)
            if "refused" in refused:
                return dict(refused["refused"])
            return {"binding": {**b, "connection_id": refused["id"]}}
        if person:
            # A call naming no account, for a person signed in to several: the one they pinned as their default;
            # with two or more and none pinned, the call asks which (ACCOUNT_CHOICE_NEEDED); with none of their
            # own, the team's default.
            choice = await self.account_choice(tenant_id, team_id, plugin, person)
            if choice is not None:
                return {"account_choice": choice}
            chosen = await self.person_default(tenant_id, team_id, plugin, person)
            if chosen is not None:
                b = {**b, "connection_id": chosen}
        if self.connections is not None:
            # A test run takes the app's sandbox account when the team has one (records.account_for).
            found = await self.connections.accounts(tenant_id, team_id, plugin_app(plugin.manifest.id))
            default = next((a for a in found if str(a["id"]) == str(b.get("connection_id") or "")), None)
            picked = account_for(default, found, run)
            b = {**b, "connection_id": picked["id"] if picked else b.get("connection_id")}
        return {"binding": b}

    async def package_checks(self, tenant_id: str, connection_id: str) -> list[dict[str, Any]]:
        """What Test connection reads on an account to learn which package apps are installed there: for each loaded
        package that runs on the account's app and requires objects, the path of each object's check rendered with
        the account's settings. Empty for an account no plugin serves, or one whose settings leave a path unset."""
        b = await self.binding_of(tenant_id, connection_id)
        host = self.plugins.get(str(b["plugin_id"])) if b else None
        if b is None or host is None:
            return []
        settings = self.settings(host, dict(b.get("settings") or {}), await self.own_settings(tenant_id, connection_id))
        out: list[dict[str, Any]] = []
        for p in self.plugins.values():
            c = p.manifest.connection
            if c.runs_on != host.manifest.id or not c.requires or c.requires_check is None:
                continue
            paths = {n: render(c.requires_check.replace("{name}", n), settings) for n in c.requires}
            if all(paths.values()):
                out.append({"id": p.manifest.id, "title": p.manifest.title, "paths": paths})
        return out

    async def for_call(
        self,
        tenant_id: str,
        team_id: str | None,
        module: Aggregate,
        run: str,
        *,
        account: str | None = None,
        accounts: Mapping[str, str] | None = None,
        person: str | None = None,
    ) -> Aggregate:
        """The module as this team's call made in `run` (test or live) sees it: the account it signs in with
        (`connection_id`, from records.account_for, and whether it is a `sandbox`), the endpoint and egress hosts
        rendered with that account's settings, and the merged settings for the transform and a Python tool. A plugin
        that is off for the team, or not loaded, is marked so the gateway refuses the call before anything else."""
        plugin = self.by_module(module)
        if plugin is None:
            return {
                **module,
                "plugin_off": f"{module['display_name']} isn't installed, so its tools are off. Ask the person who "
                "runs Ops AI at your company to install it.",
            }
        reason = await self.off_reason(tenant_id, team_id, plugin)
        if reason is not None or team_id is None:
            # Off for this team (installed, not turned on): the refusal names the app and team, so chat draws the card
            # that asks an admin to turn it on.
            off = {"app": plugin.manifest.title, "appId": plugin_app(plugin.manifest.id), "teamId": team_id}
            return {
                **module,
                "plugin_off": reason or "No team.",
                **({"app_off": off} if team_id is not None else {}),
                "connection_id": None,
                "egress_hosts": [],
            }
        b: dict[str, Any] = await self.bindings.get(tenant_id, team_id, plugin.manifest.id) or {}
        module = {**module, **tools_added_view(plugin.manifest, b)}
        runs_on = plugin.manifest.connection.runs_on
        # A package app signs in with an account of the app it runs on (`signs`), chosen as that app's own calls
        # choose one; it has no account of its own.
        signs = self.plugins.get(runs_on) if runs_on else plugin
        if signs is None:
            why = f"{plugin.manifest.title} runs inside an app this install does not have, so its tools are off."
            return {**module, "plugin_off": why, "connection_id": None, "egress_hosts": []}
        signs_b = b
        if signs is not plugin:
            reason = await self.off_reason(tenant_id, team_id, signs)
            if reason is not None:
                off = {"app": signs.manifest.title, "appId": plugin_app(signs.manifest.id), "teamId": team_id}
                return {**module, "plugin_off": reason, "app_off": off, "connection_id": None, "egress_hosts": []}
            signs_b = await self.bindings.get(tenant_id, team_id, signs.manifest.id) or {}
            if (accounts or {}).get(plugin_app(plugin.manifest.id)):
                why = (
                    f"{plugin.manifest.title} has no accounts of its own; it runs on {signs.manifest.title}'s, so a "
                    f"call names a {signs.manifest.title} account."
                )
                return {**module, "account_missing": why, "connection_id": None, "egress_hosts": []}
        chosen = await self._choose(
            tenant_id, team_id, signs, signs_b, run, account=account, accounts=accounts, person=person
        )
        if "binding" not in chosen:
            return {**module, **chosen, "connection_id": None, "egress_hosts": []}
        signs_b = chosen["binding"]
        b = signs_b if signs is plugin else b
        # The team's own plugin version, attached before the instance and header checks, so a team that is on
        # but not yet signed in still lists its own version's tools.
        team: dict[str, Any] = {}
        if self.versions and b.get("declarations"):
            decl = cast(dict[str, Any], b["declarations"])
            team = {"plugin_tools": tools_of(decl), "plugin_headers": declared_headers(decl)}
        module = {**module, **team}
        # The account the call signs in with picks the instance and hosts, so a call never mixes one account's
        # sign-in with another's address.
        conn = (
            await self.connections.get(tenant_id, str(signs_b["connection_id"]))
            if self.connections and signs_b.get("connection_id")
            else None
        )
        module = {**module, "sandbox": bool((conn or {}).get("sandbox"))}
        if signs is not plugin:
            missing = missing_objects(conn, plugin.manifest.id)
            if missing:
                why = (
                    f"{plugin.manifest.title} is not installed in {signs.manifest.title}'s account "
                    f"{(conn or {}).get('account_name') or (conn or {}).get('name')}: {', '.join(missing)} not found. "
                    "Pick an account where it is installed, or install it there and run Test on the account."
                )
                return {**module, "package_missing": why, "connection_id": None, "egress_hosts": []}
        own = own_and_registration(conn)
        settings = self.settings(signs, dict(signs_b.get("settings") or {}), own)
        if signs is not plugin:
            settings |= self.settings(plugin, dict(b.get("settings") or {}))
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
            # No instance yet is not the plugin being off. On an app each person signs in to, the team
            # account is not required first: this person signs in to the account.
            connection_id = signs_b.get("connection_id")
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
                # Named as an app off for the team is, so chat shows who signs the team account in.
                "team_sign_in": {
                    "app": plugin.manifest.title,
                    "appId": plugin_app(plugin.manifest.id),
                    "teamId": team_id,
                },
                "connection_id": None,
                "egress_hosts": [],
            }
        return {
            **module,
            # For this call the module is the calling team's: its connection is the team's (the sign-in check reads
            # the module's team), and a held write is decided in the team, as for any workspace-level module.
            "team_id": team_id,
            "connection_id": signs_b.get("connection_id"),
            "endpoint": endpoint,
            "egress_hosts": hosts,
            "plugin_settings": settings,
            "plugin_team": team_id,
        }

    async def _look_up(
        self, tenant_id: str, m: Manifest, lookup: AfterSignIn, settings: Mapping[str, Any], token: str
    ) -> tuple[str, str | None]:
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
            doc = r.json()
        except ValueError:
            doc = None
        found = at(doc, lookup.read) if doc is not None else None
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
        # The same answer often names who signed in (Salesforce's userinfo: preferred_username, email).
        return value, person_named(doc)

    def operation(self, module: Mapping[str, Any], op: dict[str, Any]) -> dict[str, Any]:
        """The operation as this call runs it, from the loaded manifest rather than the module row, which is written
        once per tenant and holds no team's settings: the tool's amount limit, its headers rendered from the
        call's settings, and a form tool's form. Unchanged for a plugin that is off for the call or not loaded."""
        plugin = self.by_module(module)
        tools = cast(dict[str, Tool] | None, module.get("plugin_tools"))
        if plugin is None or (module.get("plugin_off") and tools is None):
            return op
        m = plugin.manifest
        name = str(op["name"]).removeprefix(f"{m.short}_")
        headers: Mapping[str, str] = m.headers
        if tools is not None:
            # The team's version: the op as that version declared it, under the row's id; a tool it lacks is
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
            # Where the system reports a failure inside a 200, read by both executors on every JSON answer.
            "error_when": error_rule(m),
        }
        if tool.request is not None and tool.request.form is not None:
            # The manifest's `form` is a form body, the one form path a builder's tool takes too.
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
        sign-in, if the plugin has one, fills its setting. `own` is a person's own sign-in, which may not
        change what the team's holds (`settle_at_sign_in`). Nothing is saved until every check passes, then all of it
        on the account. Returns where Test connection reads, the instance and the plugin's health-check path, and
        under SIGNED_IN_AS whom the lookup named."""
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
        named: str | None = None
        if lookup is not None:
            now = self.settings(plugin, dict(b.get("settings") or {}), {**held, **read})
            token = str(answer.get("access_token") or "")
            read[lookup.setting], named = await self._look_up(tenant_id, m, lookup, now, token)
        read = settle_at_sign_in(held, read, own=own)
        # Saved as the signed-in account's own: a sandbox sign-in leaves the live account's instance as it was.
        if read and self.connections is not None:
            await self.connections.set_plugin_settings(tenant_id, connection_id, read)
        values = await self.own_settings(tenant_id, connection_id) or {**held, **read}
        merged = self.settings(plugin, dict(b.get("settings") or {}), values)
        endpoint = render(m.endpoint, merged)
        check = m.connection.health_check
        said = {SIGNED_IN_AS: named} if named else {}
        if endpoint is None or check is None:
            return said or None
        origin = urlsplit(endpoint)
        path = render(check.path, merged)
        return {"baseUrl": f"{origin.scheme}://{origin.netloc}", **({"testPath": path} if path else {}), **said}
