"""Each team's part of a plugin: whether the team turned it on, the team's connection and the team's settings.

A plugin's tools are one workspace-level module (no team owns it), which holds one connection, one endpoint and
one egress list for every team. So none of those live on the module: the gateway reads them from the calling team's
binding on each call, and a team with no binding, or with its binding off, does not see the plugin at all."""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa
from pydantic import JsonValue

from ops_service_kit.http import Out
from ops_service_kit.ids import now_iso
from ops_store import Guarantee, isolation
from ops_store.dialect import upsert
from ops_store.rows import one, rows
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.store import Store
from ops_store.team_scope import acting_as, any_team, team_visible

from .app_cards import forget_cards
from .modules import metadata
from .team_defaults import team_defaults
from .tenancy import ROLE

plugin_bindings = sa.Table(
    "plugin_bindings",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), primary_key=True),
    sa.Column("plugin_id", sa.String(120), primary_key=True),
    sa.Column("enabled", sa.Boolean, nullable=False),
    sa.Column("connection_id", sa.String(64)),
    # The team's settings layer; fields read from the token (instance_url) are written here at sign-in.
    sa.Column("settings", sa.JSON, nullable=False),
    sa.Column("updated_by", sa.String(320), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    # The plugin version the team took: its number, the digest of its tool declarations and the declarations
    # themselves, which each call is built from until the team takes a newer one. Null until the team takes one.
    sa.Column("version", sa.String(40)),
    sa.Column("digest", sa.String(64)),
    sa.Column("declarations", sa.JSON),
    # The tools the team switched on, by their name in the plugin; null keeps every tool on (bindings made before the
    # switch). A call to a tool off for the team is refused at the gateway.
    sa.Column("tools_on", sa.JSON),
    # The `asked: config` values the team set on Ops AI's own app (the install's OAuth client), and each one's mode as
    # app_credentials.setting_modes holds it; null for none.
    sa.Column("config_settings", sa.JSON),
    sa.Column("setting_modes", sa.JSON),
    # One team's row, never read across teams: the gateway reads the calling team's only.
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


# Why a binding is found across a tenant's teams: a sign-in names the connection, not the team, so the binding naming it
# is found, then used for its own team only.
BINDING_BY_CONNECTION = "the sign-in on a plugin's connection finds the one binding that names it"
# Why every team's binding of one plugin is read: the installed version is stamped on each one that has none.
STAMP_VERSIONS = "stamping a plugin's installed version on each team's binding that has none"


class PluginBinding(Out):
    """One team's binding of one plugin, every column of plugin_bindings."""

    tenant_id: str
    team_id: str
    plugin_id: str
    enabled: bool
    connection_id: str | None
    settings: dict[str, JsonValue]
    updated_by: str
    updated_at: str
    version: str | None
    digest: str | None
    declarations: dict[str, JsonValue] | None
    tools_on: list[str] | None
    config_settings: dict[str, JsonValue] | None
    setting_modes: dict[str, str] | None


class PluginBindings(Store):
    # One row per (tenant, team, plugin): a save is an upsert on that key, so two saves at once leave one row.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})
    role = ROLE

    async def get(self, tenant_id: str, team_id: str, plugin_id: str) -> PluginBinding | None:
        t = plugin_bindings
        with acting_as(team_id):
            q = sa.select(t).where(t.c.tenant_id == tenant_id, team_visible(t), t.c.plugin_id == plugin_id)
        with isolation.scope(tenant_id, team_id):
            async with self.tx() as c:
                return await one(c, q, PluginBinding)

    async def of_team(self, tenant_id: str, team_id: str) -> dict[str, PluginBinding]:
        t = plugin_bindings
        with acting_as(team_id):
            q = sa.select(t).where(t.c.tenant_id == tenant_id, team_visible(t))
        with isolation.scope(tenant_id, team_id):
            async with self.tx() as c:
                found = await rows(c, q, PluginBinding)
        return {b.plugin_id: b for b in found}

    async def by_connection(self, tenant_id: str, connection_id: str) -> PluginBinding | None:
        t = plugin_bindings
        # The first by key: a connection names one team's binding, but nothing in the table forbids a second.
        q = (
            sa.select(t)
            .where(t.c.tenant_id == tenant_id, any_team(t, BINDING_BY_CONNECTION), t.c.connection_id == connection_id)
            .order_by(t.c.team_id, t.c.plugin_id)
            .limit(1)
        )
        with isolation.tenant_wide(BINDING_BY_CONNECTION, tenant_id=tenant_id):
            async with self.tx() as c:
                return await one(c, q, PluginBinding)

    async def of_plugin(self, tenant_id: str, plugin_id: str) -> list[PluginBinding]:
        """Every team's binding of one plugin, for stamping the installed version on those that have none."""
        t = plugin_bindings
        q = sa.select(t).where(t.c.tenant_id == tenant_id, any_team(t, STAMP_VERSIONS), t.c.plugin_id == plugin_id)
        with isolation.tenant_wide(STAMP_VERSIONS, tenant_id=tenant_id):
            async with self.tx() as c:
                return await rows(c, q, PluginBinding)

    async def take(
        self,
        tenant_id: str,
        team_id: str,
        plugin_id: str,
        *,
        version: str,
        digest: str,
        declarations: dict[str, JsonValue],
    ) -> bool:
        """Records the plugin version a team runs on its existing binding; False when the team has no binding."""
        t = plugin_bindings
        with acting_as(team_id):
            q = (
                t.update()
                .where(t.c.tenant_id == tenant_id, team_visible(t), t.c.plugin_id == plugin_id)
                .values(version=version, digest=digest, declarations=declarations, updated_at=now_iso())
            )
        with isolation.scope(tenant_id, team_id):
            async with self.tx() as c:
                return (await c.execute(q)).rowcount > 0

    async def set_tools(self, tenant_id: str, team_id: str, plugin_id: str, tools_on: list[str]) -> bool:
        """Records the tools the team switched on; False when the team has no binding of the plugin."""
        t = plugin_bindings
        with acting_as(team_id):
            q = (
                t.update()
                .where(t.c.tenant_id == tenant_id, team_visible(t), t.c.plugin_id == plugin_id)
                .values(tools_on=sorted(set(tools_on)), updated_at=now_iso())
            )
        with isolation.scope(tenant_id, team_id):
            async with self.tx() as c:
                return (await c.execute(q)).rowcount > 0

    async def set_config(
        self,
        tenant_id: str,
        team_id: str,
        plugin_id: str,
        values: dict[str, JsonValue],
        modes: dict[str, str],
        *,
        by: str,
    ) -> bool:
        """Records the team's values on Ops AI's app and their modes; False when the team has no binding."""
        t = plugin_bindings
        with acting_as(team_id):
            q = (
                t.update()
                .where(t.c.tenant_id == tenant_id, team_visible(t), t.c.plugin_id == plugin_id)
                .values(
                    config_settings=values or None, setting_modes=modes or None, updated_by=by, updated_at=now_iso()
                )
            )
        with isolation.scope(tenant_id, team_id):
            async with self.tx() as c:
                return (await c.execute(q)).rowcount > 0

    async def put(
        self,
        tenant_id: str,
        team_id: str,
        plugin_id: str,
        *,
        enabled: bool,
        connection_id: str | None,
        settings: dict[str, JsonValue],
        by: str,
    ) -> None:
        # The version and tools columns are not named here, so an upsert leaves what the team took and chose as it is.
        values = {
            "tenant_id": tenant_id,
            "team_id": team_id,
            "plugin_id": plugin_id,
            "enabled": enabled,
            "connection_id": connection_id,
            "settings": settings,
            "updated_by": by,
            "updated_at": now_iso(),
        }
        with isolation.scope(tenant_id, team_id):
            async with self.tx() as c:
                await c.execute(upsert(c, plugin_bindings, values, keys=["tenant_id", "team_id", "plugin_id"]))
                # Turning a plugin on or off can add or take away its card when the install no longer holds it.
                await forget_cards(c, tenant_id, team_defaults.c.team_id == team_id)
