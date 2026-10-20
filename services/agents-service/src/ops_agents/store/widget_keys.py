"""Widget mint keys (c-131): the one credential a bank's server uses to mint widget sessions for one deployment.

A key reads `wk.<tenant>.<key id>.<secret>`: the tenant lets the mint route set row-level security before it reads the
key, and only the secret's SHA-256 is stored. A key mints for its own deployment and nothing else, so a leak is
contained to that one chat; revoking it stops it at once, and it mints nothing after `expires_at`. Creating and revoking
each leave a row in widget_mint_key_audit, written in the same transaction as the change.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import new_id
from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .tenancy import current_tenant, tenant_tx

widget_mint_keys = sa.Table(
    "widget_mint_keys",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, server_default="local", index=True),
    sa.Column("deployment_id", sa.String(64), nullable=False, index=True),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("secret_hash", sa.String(64), nullable=False),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("last_used_at", sa.String(32)),
    sa.Column("revoked_at", sa.String(32)),
    sa.Column("expires_at", sa.String(32)),
    info=TENANT_SCOPED,
)

widget_mint_key_audit = sa.Table(
    "widget_mint_key_audit",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, server_default="local", index=True),
    sa.Column("deployment_id", sa.String(64), nullable=False, index=True),
    sa.Column("key_id", sa.String(64), nullable=False),
    sa.Column("action", sa.String(16), nullable=False),
    sa.Column("actor", sa.String(320), nullable=False),
    sa.Column("at", sa.String(32), nullable=False),
    info=TENANT_SCOPED,
)


def _audit(deployment_id: str, key_id: str, action: str, actor: str, at: str) -> sa.Insert:
    return widget_mint_key_audit.insert().values(
        id=new_id("wka"), deployment_id=deployment_id, key_id=key_id, action=action, actor=actor, at=at
    )


class WidgetKeys:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def add(self, row: dict[str, Any]) -> None:
        async with tenant_tx(self.engine) as c:
            await c.execute(widget_mint_keys.insert().values(**row))
            await c.execute(_audit(row["deployment_id"], row["id"], "created", row["created_by"], row["created_at"]))

    async def get(self, key_id: str) -> dict[str, Any] | None:
        q = widget_mint_keys.select().where(
            widget_mint_keys.c.id == key_id, widget_mint_keys.c.tenant_id == current_tenant()
        )
        async with tenant_tx(self.engine) as c:
            r = (await c.execute(q)).mappings().first()
        return dict(r) if r is not None else None

    async def for_deployment(self, deployment_id: str) -> list[dict[str, Any]]:
        q = (
            widget_mint_keys.select()
            .where(widget_mint_keys.c.deployment_id == deployment_id, widget_mint_keys.c.tenant_id == current_tenant())
            .order_by(widget_mint_keys.c.created_at.desc())
        )
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def active_counts(self, deployment_ids: list[str]) -> dict[str, int]:
        """Unrevoked keys per deployment, for the deployments list; a deployment with none is absent."""
        if not deployment_ids:
            return {}
        q = (
            sa.select(widget_mint_keys.c.deployment_id, sa.func.count())
            .where(
                widget_mint_keys.c.deployment_id.in_(deployment_ids),
                widget_mint_keys.c.tenant_id == current_tenant(),
                widget_mint_keys.c.revoked_at.is_(None),
            )
            .group_by(widget_mint_keys.c.deployment_id)
        )
        async with tenant_tx(self.engine) as c:
            return {str(d): int(n) for d, n in (await c.execute(q)).all()}

    async def revoke(self, deployment_id: str, key_id: str, at: str, actor: str) -> bool:
        """False when the deployment has no such key, or it was revoked already."""
        q = (
            widget_mint_keys.update()
            .where(
                widget_mint_keys.c.id == key_id,
                widget_mint_keys.c.deployment_id == deployment_id,
                widget_mint_keys.c.tenant_id == current_tenant(),
                widget_mint_keys.c.revoked_at.is_(None),
            )
            .values(revoked_at=at)
        )
        async with tenant_tx(self.engine) as c:
            if (await c.execute(q)).rowcount != 1:
                return False
            await c.execute(_audit(deployment_id, key_id, "revoked", actor, at))
            return True

    async def used(self, key_id: str, at: str) -> None:
        q = (
            widget_mint_keys.update()
            .where(widget_mint_keys.c.id == key_id, widget_mint_keys.c.tenant_id == current_tenant())
            .values(last_used_at=at)
        )
        async with tenant_tx(self.engine) as c:
            await c.execute(q)

    async def previewed(self, deployment_id: str, actor: str, at: str) -> None:
        """A console preview of the deployment: in the same audit as the keys, since it also mints a session."""
        async with tenant_tx(self.engine) as c:
            await c.execute(_audit(deployment_id, "preview", "preview", actor, at))

    async def audit(self, deployment_id: str) -> list[dict[str, Any]]:
        q = (
            widget_mint_key_audit.select()
            .where(
                widget_mint_key_audit.c.deployment_id == deployment_id,
                widget_mint_key_audit.c.tenant_id == current_tenant(),
            )
            .order_by(widget_mint_key_audit.c.at.desc())
        )
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]
