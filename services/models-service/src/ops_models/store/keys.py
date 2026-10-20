"""Model keys: one per identity, with its budget, its spend and a hash of its secret (plus the previous hash during a
rotation's overlap), and each tenant's share of a key one service spends for many tenants (c-251)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

import sqlalchemy as sa

from ops_store import Guarantee
from ops_store.database import Database
from ops_store.dialect import insert_ignore, locked

from .tables import model_key_tenants as shares
from .tables import model_keys as t


class ModelKeys:
    # Spend is added in the database (spent = spent + n), so concurrent calls never lose one another's spend; a rotation
    # locks the key's row while it moves the secret to the previous slot (CAS, TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, db: Database) -> None:
        self.db = db

    async def all(self) -> list[dict[str, Any]]:
        async with self.db.connect() as c:
            return [dict(r) for r in (await c.execute(t.select().order_by(t.c.id))).mappings()]

    async def get(self, key_id: str) -> dict[str, Any] | None:
        async with self.db.connect() as c:
            row = (await c.execute(t.select().where(t.c.id == key_id))).mappings().first()
        return dict(row) if row is not None else None

    async def by_secret(self, digest: str, now: datetime) -> dict[str, Any] | None:
        """The key whose secret hashes to `digest`, or whose previous secret does and is still inside its overlap."""
        previous = sa.and_(t.c.previous_secret_hash == digest, t.c.previous_valid_until > now)
        async with self.db.connect() as c:
            row = (await c.execute(t.select().where(sa.or_(t.c.secret_hash == digest, previous)))).mappings().first()
        return dict(row) if row is not None else None

    async def issue(self, row: Mapping[str, Any]) -> bool:
        """Adds a key; False, and nothing written, when the identity has one."""
        async with self.db.begin() as c:
            if (await c.execute(sa.select(t.c.id).where(t.c.id == row["id"]))).first():
                return False
            await c.execute(t.insert().values(**row))
        return True

    async def rotate(self, key_id: str, secret_hash: str, previous_valid_until: datetime, now: datetime) -> bool:
        """Gives the key a new secret hash and keeps the old one valid until `previous_valid_until`; False when there
        is no such key."""
        async with self.db.begin() as c:
            row = (await c.execute(locked(t.select().where(t.c.id == key_id), t))).mappings().first()
            if row is None:
                return False
            await c.execute(
                t.update()
                .where(t.c.id == key_id)
                .values(
                    secret_hash=secret_hash,
                    previous_secret_hash=row["secret_hash"],
                    previous_valid_until=previous_valid_until,
                    rotated_at=now,
                )
            )
        return True

    async def tenant_share(self, key_id: str, tenant_id: str, budget: Decimal) -> dict[str, Any]:
        """The tenant's row on a per-tenant key, made at `budget` the first time the tenant spends."""
        where = (shares.c.key_id == key_id, shares.c.tenant_id == tenant_id)
        async with self.db.begin() as c:
            row = {"key_id": key_id, "tenant_id": tenant_id, "budget": budget, "spent": Decimal(0)}
            await c.execute(insert_ignore(c, shares, row, keys=["key_id", "tenant_id"]))
            return dict((await c.execute(shares.select().where(*where))).mappings().one())

    async def spend(self, key_id: str, amount: Decimal, *, tenant_id: str | None = None) -> None:
        """Adds `amount` to the key's spend and, for a per-tenant key, to the tenant's share."""
        async with self.db.begin() as c:
            await c.execute(t.update().where(t.c.id == key_id).values(spent=t.c.spent + amount))
            if tenant_id is not None:
                await c.execute(
                    shares.update()
                    .where(shares.c.key_id == key_id, shares.c.tenant_id == tenant_id)
                    .values(spent=shares.c.spent + amount)
                )

    async def ensure(self, row: Mapping[str, Any]) -> None:
        """Adds the key unless the identity has one, which keeps its secret and its spend."""
        async with self.db.begin() as c:
            await c.execute(insert_ignore(c, t, row, keys=["id"]))

    async def set_tenant_budget(self, key_id: str, budget: Decimal) -> None:
        """Makes the key spend per tenant at `budget` each, unless it already has a tenant budget."""
        async with self.db.begin() as c:
            await c.execute(
                t.update().where(t.c.id == key_id, t.c.tenant_budget.is_(None)).values(tenant_budget=budget)
            )
