"""API keys as a team admin sees them. The secret's hash is written once at creation and never read back here;
verifying a presented key is `IdentityStore.key`, on the introspection path."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa

from ops_store import Guarantee

from .audit import record
from .members import Actor
from .tables import api_keys, teams, users
from .tenancy import TenantDb

_LISTED = (
    api_keys.c.id,
    api_keys.c.name,
    api_keys.c.prefix,
    api_keys.c.scopes,
    users.c.name.label("created_by"),
    api_keys.c.created_at,
    api_keys.c.last_used_at,
    api_keys.c.expires_at,
    api_keys.c.revoked_at,
    api_keys.c.disabled_at,
    teams.c.name.label("team"),
)


class KeyStore:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    def _listing(self, team_id: str) -> Any:
        return (
            sa.select(*_LISTED)
            .join(teams, teams.c.id == api_keys.c.team_id)
            .join(users, users.c.id == api_keys.c.created_by)
            .where(api_keys.c.team_id == team_id)
            .order_by(api_keys.c.created_at.desc(), api_keys.c.id)
        )

    async def list(self, tenant_id: str, team_id: str) -> list[dict[str, Any]]:
        async with self.db.tenant_tx(tenant_id) as c:
            return [dict(r) for r in (await c.execute(self._listing(team_id))).mappings().all()]

    async def create(
        self,
        actor: Actor,
        *,
        key_id: str,
        name: str,
        secret_hash: str,
        scopes: list[str],
        expires_at: str | None,
        at: str,
    ) -> dict[str, Any]:
        async with self.db.tenant_tx(actor.tenant_id) as c:
            await c.execute(
                api_keys.insert().values(
                    id=key_id,
                    tenant_id=actor.tenant_id,
                    team_id=actor.team_id,
                    name=name,
                    prefix=key_id,
                    secret_hash=secret_hash,
                    scopes=scopes,
                    created_by=actor.user_id,
                    created_at=at,
                    expires_at=expires_at,
                )
            )
            await _audit(c, actor, "key.create", key_id, {"name": name, "scopes": scopes})
            return dict((await c.execute(self._listing(actor.team_id).where(api_keys.c.id == key_id))).mappings().one())

    async def revoke(self, actor: Actor, key_id: str, *, at: str) -> dict[str, Any] | None:
        """None when the team has no such key; revoking a revoked key changes nothing and writes no entry."""
        async with self.db.tenant_tx(actor.tenant_id) as c:
            done = await c.execute(
                api_keys.update()
                .where(api_keys.c.id == key_id, api_keys.c.team_id == actor.team_id, api_keys.c.revoked_at.is_(None))
                .values(revoked_at=at)
            )
            if done.rowcount == 1:
                await _audit(c, actor, "key.revoke", key_id, {})
            row = (await c.execute(self._listing(actor.team_id).where(api_keys.c.id == key_id))).mappings().first()
            return dict(row) if row else None


async def _audit(c: Any, actor: Actor, action: str, key_id: str, detail: dict[str, Any]) -> None:
    await record(
        c,
        tenant_id=actor.tenant_id,
        team_id=actor.team_id,
        actor=actor.user_id,
        action=action,
        target_kind="api_key",
        target_id=key_id,
        request_id=actor.request_id,
        detail=detail,
    )
