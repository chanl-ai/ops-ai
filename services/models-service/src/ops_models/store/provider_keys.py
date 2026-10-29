"""An account's model provider keys, sealed: every read and write names the tenant, and a value leaves only through
`value`, which models-service's provider calls use. The tenant and the key's name are the cipher's associated data,
so a sealed value copied to another name or tenant does not decrypt."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa

from ops_policy import Cipher, context_of
from ops_store import Guarantee
from ops_store.database import Database
from ops_store.dialect import db_now, locked

from .tables import provider_keys as t

META = (t.c.name, t.c.version, t.c.created_by, t.c.created_at, t.c.rotated_at)


class ProviderKeyStore:
    # A save locks the key's row while it moves the version on, so two saves of one name never both write version 2.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, db: Database, cipher: Cipher) -> None:
        self.db = db
        self.cipher = cipher

    async def listed(self, tenant_id: str) -> list[dict[str, Any]]:
        """Each key's name and history, never its value."""
        async with self.db.connect() as c:
            rows = await c.execute(sa.select(*META).where(t.c.tenant_id == tenant_id).order_by(t.c.name))
            return [dict(r) for r in rows.mappings()]

    async def save(self, tenant_id: str, name: str, value: str, *, by: str) -> tuple[dict[str, Any], bool]:
        """Creates the key or replaces its value; returns its history and whether it was new."""
        sealed = self.cipher.encrypt(value, context=context_of(tenant_id, name))
        mine = sa.and_(t.c.tenant_id == tenant_id, t.c.name == name)
        async with self.db.begin() as c:
            found = (await c.execute(locked(sa.select(t.c.version).where(mine), t))).first()
            if found is None:
                row = {"tenant_id": tenant_id, "name": name, "ciphertext": sealed, "version": 1, "created_by": by}
                await c.execute(t.insert().values(**row))
            else:
                change = {"ciphertext": sealed, "version": found.version + 1, "rotated_at": db_now()}
                await c.execute(t.update().where(mine).values(**change))
            saved = (await c.execute(sa.select(*META).where(mine))).mappings().one()
        return dict(saved), found is None

    async def delete(self, tenant_id: str, name: str) -> bool:
        async with self.db.begin() as c:
            gone = await c.execute(t.delete().where(t.c.tenant_id == tenant_id, t.c.name == name))
        return gone.rowcount > 0

    async def value(self, tenant_id: str, name: str) -> str | None:
        """The key's value, or None when the account holds none by that name. A value that does not decrypt (the
        secrets key changed) raises CipherError rather than reaching a provider as garbage."""
        async with self.db.connect() as c:
            sealed = await c.scalar(sa.select(t.c.ciphertext).where(t.c.tenant_id == tenant_id, t.c.name == name))
        if sealed is None:
            return None
        return self.cipher.decrypt(sealed, context=context_of(tenant_id, name))
