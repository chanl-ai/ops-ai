"""API keys as a team admin sees them. The secret's hash is written once at creation and never read back here;
verifying a presented key is `IdentityStore.key`, on the introspection path."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.http import Out
from ops_service_kit.listing import ListParams
from ops_store import Guarantee
from ops_store.listing import ListPage, list_page
from ops_store.rows import Select, one, rows

from .audit import record
from .key_events import announce, change_keys
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
    api_keys.c.team_id,
    api_keys.c.target_kind,
    api_keys.c.target_id,
    api_keys.c.target_version,
    api_keys.c.revision,
)


class KeyRow(Out):
    """A key as `_LISTED` selects it: never its secret's hash."""

    id: str
    name: str
    prefix: str
    scopes: list[str]
    created_by: str
    created_at: str
    last_used_at: str | None
    expires_at: str | None
    revoked_at: str | None
    disabled_at: str | None
    team: str
    team_id: str
    target_kind: str | None
    target_id: str | None
    target_version: int | None
    revision: int


class KeyStore(TenantDb):
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    def _listing(self, team_id: str | None) -> Select:
        q = (
            sa.select(*_LISTED)
            .join(teams, teams.c.id == api_keys.c.team_id)
            .join(users, users.c.id == api_keys.c.created_by)
            .order_by(api_keys.c.created_at.desc(), api_keys.c.id)
        )
        return q if team_id is None else q.where(api_keys.c.team_id == team_id)

    async def page(self, tenant_id: str, team_id: str, params: ListParams) -> ListPage:
        """The team's keys on the shared list contract, newest first: searched on name, filtered by `targetKind`
        and `targetId` (an MCP link's Keys tab lists the keys made for it), all in SQL."""
        q = self._listing(team_id).order_by(None)
        by = {"targetKind": api_keys.c.target_kind, "targetId": api_keys.c.target_id}
        async with self.tenant_tx(tenant_id) as c:
            return await list_page(
                c,
                q,
                params,
                search=[api_keys.c.name],
                default_sort=api_keys.c.created_at.desc(),
                filters=by,
            )

    async def every(self, tenant_id: str) -> list[KeyRow]:
        """Every team's keys in the workspace, for a service's list of API channels."""
        async with self.tenant_tx(tenant_id) as c:
            return await rows(c, self._listing(None), KeyRow)

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
        target: Mapping[str, JsonValue] | None = None,
    ) -> KeyRow:
        async with self.tenant_tx(actor.tenant_id) as c:
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
                    target_kind=target["kind"] if target else None,
                    target_id=target["id"] if target else None,
                    target_version=target.get("version") if target else None,
                    revision=1,
                )
            )
            await announce(c, [key_id])
            given = dict(target) if target else None
            await _audit(c, actor, "key.create", key_id, {"name": name, "scopes": [*scopes], "target": given})
            made = await one(c, self._listing(actor.team_id).where(api_keys.c.id == key_id), KeyRow)
            assert made is not None, key_id  # written above, in this transaction
            return made

    async def revoke(self, actor: Actor, key_id: str, *, at: str) -> KeyRow | None:
        """None when the team has no such key; revoking a revoked key changes nothing and writes no entry."""
        async with self.tenant_tx(actor.tenant_id) as c:
            k = api_keys.c
            done = await change_keys(
                c, sa.and_(k.id == key_id, k.team_id == actor.team_id, k.revoked_at.is_(None)), {"revoked_at": at}
            )
            if done:
                await _audit(c, actor, "key.revoke", key_id, {})
            return await one(c, self._listing(actor.team_id).where(api_keys.c.id == key_id), KeyRow)


async def _audit(c: AsyncConnection, actor: Actor, action: str, key_id: str, detail: Mapping[str, JsonValue]) -> None:
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
