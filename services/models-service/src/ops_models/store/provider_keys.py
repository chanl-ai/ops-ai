"""An account's model provider keys: every read and write names the tenant, each value is put and read through the
credential store (`ops_policy.credentials`) and the row keeps only its reference, and a value leaves only through
`value`, which models-service's provider calls use. The store holds each value under the tenant and the key's name, so
a reference copied to another name or tenant does not open."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa

from ops_policy import CredentialStore, context_of
from ops_store import Guarantee, isolation
from ops_store.database import Database
from ops_store.dialect import db_now, locked

from .tables import provider_keys as t

# The role every provider key transaction runs as (models_0009): row-level security holds it to the caller's tenant.
ROLE = "ops_models_tenant"

META = (t.c.name, t.c.version, t.c.created_by, t.c.created_at, t.c.rotated_at)


class ProviderKeyStore:
    # A save locks the key's row while it moves the version on, so two saves of one name never both write version 2.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, db: Database, credentials: CredentialStore) -> None:
        self.db = db
        self.credentials = credentials

    async def listed(self, tenant_id: str) -> list[dict[str, Any]]:
        """Each key's name and history, never its value."""
        async with isolation.isolated_tx(self.db, role=ROLE) as c:
            rows = await c.execute(sa.select(*META).where(t.c.tenant_id == tenant_id).order_by(t.c.name))
            return [dict(r) for r in rows.mappings()]

    async def save(self, tenant_id: str, name: str, value: str, *, by: str) -> tuple[dict[str, Any], bool]:
        """Creates the key or replaces its value; returns its history and whether it was new. A replaced value is
        dropped from the credential store once the row names the new one."""
        context = context_of(tenant_id, name)
        ref = await self.credentials.put(value, context=context)
        mine = sa.and_(t.c.tenant_id == tenant_id, t.c.name == name)
        async with isolation.isolated_tx(self.db, role=ROLE) as c:
            found = (await c.execute(locked(sa.select(t.c.version).where(mine), t))).first()
            # Read under the row lock just taken, so two saves each drop the value they replaced.
            old = await c.scalar(sa.select(t.c.ciphertext).where(mine)) if found is not None else None
            if found is None:
                row = {"tenant_id": tenant_id, "name": name, "ciphertext": ref, "version": 1, "created_by": by}
                await c.execute(t.insert().values(**row))
            else:
                change = {"ciphertext": ref, "version": found.version + 1, "rotated_at": db_now()}
                await c.execute(t.update().where(mine).values(**change))
            saved = (await c.execute(sa.select(*META).where(mine))).mappings().one()
        if old is not None:
            await self.credentials.delete(str(old), context=context)
        return dict(saved), found is None

    async def delete(self, tenant_id: str, name: str) -> bool:
        async with isolation.isolated_tx(self.db, role=ROLE) as c:
            gone = await c.scalar(
                t.delete().where(t.c.tenant_id == tenant_id, t.c.name == name).returning(t.c.ciphertext)
            )
        if gone is None:
            return False
        await self.credentials.delete(str(gone), context=context_of(tenant_id, name))
        return True

    async def value(self, tenant_id: str, name: str) -> str | None:
        """The key's value, or None when the account holds none by that name. A value that does not open (the secrets
        key changed, or the vault lost it) raises CipherError rather than reaching a provider as garbage."""
        async with isolation.isolated_tx(self.db, role=ROLE) as c:
            ref = await c.scalar(sa.select(t.c.ciphertext).where(t.c.tenant_id == tenant_id, t.c.name == name))
        if ref is None:
            return None
        return await self.credentials.get(ref, context=context_of(tenant_id, name))
