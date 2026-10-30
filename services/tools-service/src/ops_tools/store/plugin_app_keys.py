"""The platform's own OAuth app secret for a plugin (c-565), one per account and plugin, sealed with the settings'
secrets key: the app an install registers once with a vendor, which every team uses unless it brings its own.

It belongs to no team. A team is the boundary and nothing crosses teams (owner, 2026-10-29), so the secret is not a
team's secret that other teams read: it lives at the account, set by an account admin only, as model provider keys
do in models-service. Its value leaves only through `value`, which a sign-in's token exchange uses; no route returns
it. The tenant and the plugin id are the cipher's associated data, so a sealed value copied to another plugin or
tenant does not decrypt. A value is kept a minute so a sign-in does not wait on the database, and a save or a delete
drops it at once."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_policy import Cipher, context_of
from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.dialect import upsert

from .modules import metadata

KEEP_S = 60.0

plugin_app_keys = sa.Table(
    "plugin_app_keys",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("plugin_id", sa.String(120), primary_key=True),
    sa.Column("ciphertext", sa.Text, nullable=False),
    sa.Column("updated_by", sa.String(320), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
)


class PluginAppKeys:
    # One row per (tenant, plugin): a save is an upsert on that key, so two saves at once leave one row.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, engine: AsyncEngine, cipher: Cipher, clock: Callable[[], float] = time.monotonic) -> None:
        self.engine = engine
        self.cipher = cipher
        self.clock = clock
        self._kept: dict[tuple[str, str], tuple[float, str | None]] = {}

    async def save(self, tenant_id: str, plugin_id: str, value: str, *, by: str) -> dict[str, Any]:
        sealed = self.cipher.encrypt(value, context=context_of(tenant_id, plugin_id))
        row = {"tenant_id": tenant_id, "plugin_id": plugin_id, "ciphertext": sealed, "updated_by": by}
        row["updated_at"] = now_iso()
        async with self.engine.begin() as c:
            await c.execute(upsert(c, plugin_app_keys, row, keys=["tenant_id", "plugin_id"]))
        self._kept.pop((tenant_id, plugin_id), None)
        return {"pluginId": plugin_id, "updatedBy": by, "updatedAt": row["updated_at"]}

    async def delete(self, tenant_id: str, plugin_id: str) -> bool:
        mine = sa.and_(plugin_app_keys.c.tenant_id == tenant_id, plugin_app_keys.c.plugin_id == plugin_id)
        async with self.engine.begin() as c:
            gone = await c.execute(plugin_app_keys.delete().where(mine))
        self._kept.pop((tenant_id, plugin_id), None)
        return gone.rowcount > 0

    async def held(self, tenant_id: str, plugin_id: str) -> bool:
        """Whether the account holds a secret for the plugin, for views that must never show it."""
        return await self.value(tenant_id, plugin_id) is not None

    async def value(self, tenant_id: str, plugin_id: str) -> str | None:
        key = (tenant_id, plugin_id)
        kept = self._kept.get(key)
        if kept is not None and self.clock() - kept[0] < KEEP_S:
            return kept[1]
        mine = sa.and_(plugin_app_keys.c.tenant_id == tenant_id, plugin_app_keys.c.plugin_id == plugin_id)
        async with self.engine.connect() as c:
            sealed = await c.scalar(sa.select(plugin_app_keys.c.ciphertext).where(mine))
        found = None if sealed is None else self.cipher.decrypt(sealed, context=context_of(tenant_id, plugin_id))
        self._kept[key] = (self.clock(), found)
        return found
