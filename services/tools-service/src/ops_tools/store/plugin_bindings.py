"""Each team's part of a plugin: whether the team turned it on, the team's connection and the team's settings.

A plugin's tools are one workspace-level module (no team owns it), which holds one connection, one endpoint and
one egress list for every team. So none of those live on the module: the gateway reads them from the calling team's
binding on each call, and a team with no binding, or with its binding off, does not see the plugin at all."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.dialect import upsert
from ops_store.schema import TEAM_OWNED
from ops_store.team_scope import acting_as, any_team, team_visible

from .modules import metadata

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
    # One team's row, never read across teams: the gateway reads the calling team's only.
    info=TEAM_OWNED,
)


class PluginBindings:
    # One row per (tenant, team, plugin): a save is an upsert on that key, so two saves at once leave one row.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def get(self, tenant_id: str, team_id: str, plugin_id: str) -> dict[str, Any] | None:
        t = plugin_bindings
        with acting_as(team_id):
            q = sa.select(t).where(t.c.tenant_id == tenant_id, team_visible(t), t.c.plugin_id == plugin_id)
        async with self.engine.connect() as c:
            row = (await c.execute(q)).mappings().first()
        return dict(row) if row else None

    async def of_team(self, tenant_id: str, team_id: str) -> dict[str, dict[str, Any]]:
        t = plugin_bindings
        with acting_as(team_id):
            q = sa.select(t).where(t.c.tenant_id == tenant_id, team_visible(t))
        async with self.engine.connect() as c:
            rows = (await c.execute(q)).mappings().all()
        return {str(r["plugin_id"]): dict(r) for r in rows}

    async def by_connection(self, tenant_id: str, connection_id: str) -> dict[str, Any] | None:
        t = plugin_bindings
        # A sign-in names the connection, not the team: the binding is found by it, then used for that team only.
        reason = "the sign-in on a plugin's connection finds the one binding that names it"
        q = sa.select(t).where(t.c.tenant_id == tenant_id, any_team(t, reason), t.c.connection_id == connection_id)
        async with self.engine.connect() as c:
            row = (await c.execute(q)).mappings().first()
        return dict(row) if row else None

    async def of_plugin(self, tenant_id: str, plugin_id: str) -> list[dict[str, Any]]:
        """Every team's binding of one plugin, for stamping the installed version on those that have none."""
        t = plugin_bindings
        reason = "stamping a plugin's installed version on each team's binding that has none"
        q = sa.select(t).where(t.c.tenant_id == tenant_id, any_team(t, reason), t.c.plugin_id == plugin_id)
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings().all()]

    async def take(
        self, tenant_id: str, team_id: str, plugin_id: str, *, version: str, digest: str, declarations: dict[str, Any]
    ) -> bool:
        """Records the plugin version a team runs on its existing binding; False when the team has no binding."""
        t = plugin_bindings
        with acting_as(team_id):
            q = (
                t.update()
                .where(t.c.tenant_id == tenant_id, team_visible(t), t.c.plugin_id == plugin_id)
                .values(version=version, digest=digest, declarations=declarations, updated_at=now_iso())
            )
        async with self.engine.begin() as c:
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
        async with self.engine.begin() as c:
            return (await c.execute(q)).rowcount > 0

    async def put(
        self,
        tenant_id: str,
        team_id: str,
        plugin_id: str,
        *,
        enabled: bool,
        connection_id: str | None,
        settings: dict[str, Any],
        by: str,
    ) -> dict[str, Any]:
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
        async with self.engine.begin() as c:
            await c.execute(upsert(c, plugin_bindings, values, keys=["tenant_id", "team_id", "plugin_id"]))
        return values
