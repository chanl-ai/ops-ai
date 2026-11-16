"""Model keys: one per identity, with its budget, its spend and a hash of its secret (plus the previous hash during a
rotation's overlap), and each tenant's share of a key one service spends for many tenants."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.http import ListResult, Out
from ops_service_kit.listing import ListParams
from ops_store import Guarantee
from ops_store.dialect import insert_ignore, locked
from ops_store.listing import list_page
from ops_store.rows import one
from ops_store.store import Store

from .provider_keys import ROLE
from .tables import model_key_tenants as shares
from .tables import model_keys as t

# Why keys are read and written with no tenant (`Store.install_tx`): one identity's key, spent for many tenants, found
# by a completion that authenticates by the key and often names no tenant.
MODEL_KEYS = "model_keys"


class KeyRow(Out):
    """A model key as stored, its secret's hash included: never returned by a route."""

    id: str
    kind: str
    budget: Decimal
    spent: Decimal
    rate_limit_per_minute: int
    expires_at: datetime | None
    status: str
    secret_hash: str
    previous_secret_hash: str | None
    previous_valid_until: datetime | None
    created_at: datetime
    rotated_at: datetime | None
    tenant_budget: Decimal | None
    daily_cap: Decimal | None


class ShareRow(Out):
    """One tenant's share of a per-tenant key."""

    key_id: str
    tenant_id: str
    budget: Decimal
    spent: Decimal


class KeyShares(Store):
    """Each tenant's share, run as ROLE in that tenant so the database holds the row to it. ROLE may update model_keys
    (models_0010), so a per-tenant spend moves the key's total in the same transaction."""

    role = ROLE

    async def share(self, key_id: str, tenant_id: str, budget: Decimal) -> ShareRow:
        where = (shares.c.key_id == key_id, shares.c.tenant_id == tenant_id)
        async with self.tx() as c:
            row = {"key_id": key_id, "tenant_id": tenant_id, "budget": budget, "spent": Decimal(0)}
            await c.execute(insert_ignore(c, shares, row, keys=["key_id", "tenant_id"]))
            found = await one(c, shares.select().where(*where), ShareRow)
        if found is None:
            raise LookupError(f"no share of {key_id} for the tenant after it was made")
        return found

    async def spend(self, key_id: str, tenant_id: str, amount: Decimal) -> None:
        async with self.tx() as c:
            await c.execute(t.update().where(t.c.id == key_id).values(spent=t.c.spent + amount))
            await c.execute(
                shares.update()
                .where(shares.c.key_id == key_id, shares.c.tenant_id == tenant_id)
                .values(spent=shares.c.spent + amount)
            )


class ModelKeys(Store):
    # Spend is added in the database (spent = spent + n), so concurrent calls never lose one another's spend; a rotation
    # locks the key's row while it moves the secret to the previous slot (CAS, TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(engine)
        self.shares = KeyShares(engine)

    async def page(self, params: ListParams) -> ListResult[KeyRow]:
        """One page of the keys by id; `search` matches the id, the kind or the status."""
        async with self.install_tx(MODEL_KEYS, tables=(t,)) as c:
            page = await list_page(
                c, sa.select(t), params, search=(t.c.id, t.c.kind, t.c.status), default_sort=t.c.id.asc()
            )
        return ListResult[KeyRow].model_validate(page)

    async def get(self, key_id: str) -> KeyRow | None:
        async with self.install_tx(MODEL_KEYS, tables=(t,)) as c:
            return await one(c, t.select().where(t.c.id == key_id), KeyRow)

    async def by_secret(self, digest: str, now: datetime) -> KeyRow | None:
        """The key whose secret hashes to `digest`, or whose previous secret does and is still inside its overlap."""
        previous = sa.and_(t.c.previous_secret_hash == digest, t.c.previous_valid_until > now)
        async with self.install_tx(MODEL_KEYS, tables=(t,)) as c:
            return await one(c, t.select().where(sa.or_(t.c.secret_hash == digest, previous)), KeyRow)

    async def issue(self, row: Mapping[str, Any]) -> bool:
        """Adds a key; False, and nothing written, when the identity has one."""
        async with self.install_tx(MODEL_KEYS, tables=(t,)) as c:
            if (await c.execute(sa.select(t.c.id).where(t.c.id == row["id"]))).first():
                return False
            await c.execute(t.insert().values(**row))
        return True

    async def rotate(self, key_id: str, secret_hash: str, previous_valid_until: datetime, now: datetime) -> bool:
        """Gives the key a new secret hash and keeps the old one valid until `previous_valid_until`; False when there
        is no such key."""
        async with self.install_tx(MODEL_KEYS, tables=(t,)) as c:
            held = (await c.execute(locked(sa.select(t.c.secret_hash).where(t.c.id == key_id), t))).first()
            if held is None:
                return False
            await c.execute(
                t.update()
                .where(t.c.id == key_id)
                .values(
                    secret_hash=secret_hash,
                    previous_secret_hash=held.secret_hash,
                    previous_valid_until=previous_valid_until,
                    rotated_at=now,
                )
            )
        return True

    async def tenant_share(self, key_id: str, tenant_id: str, budget: Decimal) -> ShareRow:
        """The tenant's row on a per-tenant key, made at `budget` the first time the tenant spends."""
        return await self.shares.share(key_id, tenant_id, budget)

    async def spend(self, key_id: str, amount: Decimal, *, tenant_id: str | None = None) -> None:
        """Adds `amount` to the key's spend and, for a per-tenant key, to the tenant's share, run as ROLE in that
        tenant so the database holds the share to it."""
        if tenant_id is not None:
            await self.shares.spend(key_id, tenant_id, amount)
            return
        async with self.install_tx(MODEL_KEYS, tables=(t,)) as c:
            await c.execute(t.update().where(t.c.id == key_id).values(spent=t.c.spent + amount))

    async def ensure(self, row: Mapping[str, Any]) -> None:
        """Adds the key unless the identity has one, which keeps its secret and its spend."""
        async with self.install_tx(MODEL_KEYS, tables=(t,)) as c:
            await c.execute(insert_ignore(c, t, row, keys=["id"]))

    async def set_daily_cap(self, key_id: str, cap: Decimal | None) -> None:
        """What the key may spend in one UTC day; None removes the cap."""
        async with self.install_tx(MODEL_KEYS, tables=(t,)) as c:
            await c.execute(t.update().where(t.c.id == key_id).values(daily_cap=cap))

    async def set_tenant_budget(self, key_id: str, budget: Decimal) -> None:
        """Makes the key spend per tenant at `budget` each, unless it already has a tenant budget."""
        async with self.install_tx(MODEL_KEYS, tables=(t,)) as c:
            await c.execute(
                t.update().where(t.c.id == key_id, t.c.tenant_budget.is_(None)).values(tenant_budget=budget)
            )
