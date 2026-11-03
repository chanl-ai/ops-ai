"""The platform's own OAuth app secret for a plugin, one per account and plugin, sealed with the settings'
secrets key: the app an install registers once with a vendor, which every team uses unless it brings its own.

It belongs to no team. A team is the boundary and nothing crosses teams, so the secret is not a
team's secret that other teams read: it lives at the account, set by an account admin only, as model provider keys
do in models-service. Its value leaves only through `value`, which a sign-in's token exchange uses; no route returns
it. The value is kept in the credential store (`ops_policy.credentials`) under the tenant and the plugin id, so a
reference copied to another plugin or tenant does not open; the row holds only that reference. A value is kept a
minute so a sign-in does not wait on the database, and a save or a delete drops it at once."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_policy import CredentialStore, context_of
from ops_service_kit.ids import now_iso
from ops_store import Guarantee, isolation
from ops_store.dialect import locked, upsert
from ops_store.schema import TENANT_SCOPED

from .connections import ROLE
from .modules import metadata

KEEP_S = 60.0

plugin_app_keys = sa.Table(
    "plugin_app_keys",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("plugin_id", sa.String(120), primary_key=True),
    # The credential store's reference to the secret, read and written only through it.
    sa.Column("ciphertext", sa.Text, nullable=False),
    sa.Column("updated_by", sa.String(320), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    # The account's, no team's: held to its tenant by the database, read only as ROLE.
    info=TENANT_SCOPED,
)


def _mine(tenant_id: str, plugin_id: str) -> sa.ColumnElement[bool]:
    return sa.and_(plugin_app_keys.c.tenant_id == tenant_id, plugin_app_keys.c.plugin_id == plugin_id)


class PluginAppKeys:
    # One row per (tenant, plugin): a save is an upsert on that key, so two saves at once leave one row.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(
        self, engine: AsyncEngine, credentials: CredentialStore, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.engine = engine
        self.credentials = credentials
        self.clock = clock
        self._kept: dict[tuple[str, str], tuple[float, str | None]] = {}

    async def save(self, tenant_id: str, plugin_id: str, value: str, *, by: str) -> dict[str, Any]:
        context = context_of(tenant_id, plugin_id)
        ref = await self.credentials.put(value, context=context)
        row = {"tenant_id": tenant_id, "plugin_id": plugin_id, "ciphertext": ref, "updated_by": by}
        row["updated_at"] = now_iso()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            old = await c.scalar(
                locked(sa.select(plugin_app_keys.c.ciphertext).where(_mine(tenant_id, plugin_id)), plugin_app_keys)
            )
            await c.execute(upsert(c, plugin_app_keys, row, keys=["tenant_id", "plugin_id"]))
        if old is not None:
            await self.credentials.delete(str(old), context=context)
        self._kept.pop((tenant_id, plugin_id), None)
        return {"pluginId": plugin_id, "updatedBy": by, "updatedAt": row["updated_at"]}

    async def delete(self, tenant_id: str, plugin_id: str) -> bool:
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            gone = await c.scalar(
                plugin_app_keys.delete().where(_mine(tenant_id, plugin_id)).returning(plugin_app_keys.c.ciphertext)
            )
        self._kept.pop((tenant_id, plugin_id), None)
        if gone is None:
            return False
        await self.credentials.delete(str(gone), context=context_of(tenant_id, plugin_id))
        return True

    async def held(self, tenant_id: str, plugin_id: str) -> bool:
        """Whether the account holds a secret for the plugin, for views that must never show it."""
        return await self.value(tenant_id, plugin_id) is not None

    async def value(self, tenant_id: str, plugin_id: str) -> str | None:
        key = (tenant_id, plugin_id)
        kept = self._kept.get(key)
        if kept is not None and self.clock() - kept[0] < KEEP_S:
            return kept[1]
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            ref = await c.scalar(sa.select(plugin_app_keys.c.ciphertext).where(_mine(tenant_id, plugin_id)))
        found = None if ref is None else await self.credentials.get(ref, context=context_of(tenant_id, plugin_id))
        self._kept[key] = (self.clock(), found)
        return found
