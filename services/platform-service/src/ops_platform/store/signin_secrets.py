"""A workspace's sign-in secrets: the values its providers name as `clientSecretRef` (an OIDC client secret). Each value
is put and read through the credential store (`ops_policy.credentials`) under the tenant and the name, so a sealed value
copied to another name or workspace does not open; the row keeps its history, and a value leaves only through `value`,
which the sign-in round trip uses. Every save and delete is audited in the same transaction."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa

from ops_policy import CredentialStore, context_of
from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.dialect import locked

from .audit import record
from .tables import signin_secrets as t
from .tenancy import TenantDb

META = (t.c.name, t.c.version, t.c.created_by, t.c.created_at, t.c.rotated_at)


class SignInSecretStore:
    # A save locks the name's row while it moves the version on, so two saves never both write version 2.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS, Guarantee.LOCK})

    def __init__(self, db: TenantDb, credentials: CredentialStore) -> None:
        self.db = db
        self.credentials = credentials

    async def listed(self, tenant_id: str) -> list[dict[str, Any]]:
        """Each secret's name and history, never its value."""
        async with self.db.tenant_tx(tenant_id) as c:
            rows = await c.execute(sa.select(*META).where(t.c.tenant_id == tenant_id).order_by(t.c.name))
            return [dict(r) for r in rows.mappings()]

    async def names(self, tenant_id: str) -> set[str]:
        return {str(r["name"]) for r in await self.listed(tenant_id)}

    async def save(self, tenant_id: str, name: str, value: str, *, by: str, request_id: str) -> dict[str, Any]:
        """Creates the secret or replaces its value; a replaced value is dropped from the credential store once the
        row names the new one."""
        context = context_of(tenant_id, name)
        ref = await self.credentials.put(value, context=context)
        mine = sa.and_(t.c.tenant_id == tenant_id, t.c.name == name)
        async with self.db.tenant_tx(tenant_id) as c:
            version = (await c.execute(locked(sa.select(t.c.version).where(mine), t))).scalar()
            # Read under the row lock just taken, so two saves each drop the value they replaced.
            old = await c.scalar(sa.select(t.c.ciphertext).where(mine)) if version is not None else None
            if version is None:
                await c.execute(
                    t.insert().values(
                        tenant_id=tenant_id, name=name, ciphertext=ref, version=1, created_by=by, created_at=now_iso()
                    )
                )
            else:
                await c.execute(
                    t.update().where(mine).values(ciphertext=ref, version=int(version) + 1, rotated_at=now_iso())
                )
            saved = dict((await c.execute(sa.select(*META).where(mine))).mappings().one())
            await record(
                c,
                tenant_id=tenant_id,
                team_id=None,
                actor=by,
                action="signin_secret.save",
                target_kind="signin_secret",
                target_id=name,
                request_id=request_id,
                detail={"version": saved["version"]},
            )
        if old is not None:
            await self.credentials.delete(str(old), context=context)
        return saved

    async def delete(self, tenant_id: str, name: str, *, by: str, request_id: str) -> bool:
        async with self.db.tenant_tx(tenant_id) as c:
            gone = await c.scalar(
                t.delete().where(t.c.tenant_id == tenant_id, t.c.name == name).returning(t.c.ciphertext)
            )
            if gone is None:
                return False
            await record(
                c,
                tenant_id=tenant_id,
                team_id=None,
                actor=by,
                action="signin_secret.delete",
                target_kind="signin_secret",
                target_id=name,
                request_id=request_id,
                detail={},
            )
        await self.credentials.delete(str(gone), context=context_of(tenant_id, name))
        return True

    async def value(self, tenant_id: str, name: str) -> str | None:
        """The secret's value, or None when the workspace holds none by that name."""
        async with self.db.tenant_tx(tenant_id) as c:
            ref = await c.scalar(sa.select(t.c.ciphertext).where(t.c.tenant_id == tenant_id, t.c.name == name))
        if ref is None:
            return None
        return await self.credentials.get(str(ref), context=context_of(tenant_id, name))
