"""Provider connections: where an alias version's calls go, and the name of the credential they use (never the
credential itself)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

import sqlalchemy as sa

from ops_service_kit.http import Out
from ops_store import Guarantee
from ops_store.dialect import insert_ignore
from ops_store.rows import one, rows
from ops_store.store import Store

from .tables import provider_connections as t

# Why connections are read and written with no tenant (`Store.install_tx`): one install's, used by every tenant's
# calls, including a completion that authenticates by a model key and names no tenant.
CONNECTIONS = "provider_connections"


class ProviderRow(Out):
    """A provider connection as stored."""

    id: str
    name: str
    type: str
    base_url: str | None
    key_ref: str | None
    api_version: str | None
    region: str | None
    observed_region: str | None
    created_at: str


class Providers(Store):
    # A connection's name is unique, so two creates of one name cannot both land (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    async def all(self) -> list[ProviderRow]:
        async with self.install_tx(CONNECTIONS, tables=(t,)) as c:
            return await rows(c, t.select().order_by(t.c.name), ProviderRow)

    async def get(self, provider_id: str) -> ProviderRow | None:
        async with self.install_tx(CONNECTIONS, tables=(t,)) as c:
            return await one(c, t.select().where(t.c.id == provider_id), ProviderRow)

    async def create(self, row: Mapping[str, Any]) -> bool:
        """Adds a connection; False, and nothing written, when one with the same name exists."""
        async with self.install_tx(CONNECTIONS, tables=(t,)) as c:
            if (await c.execute(sa.select(t.c.id).where(t.c.name == row["name"]))).first():
                return False
            await c.execute(t.insert().values(**row))
        return True

    async def rebind(self, provider_id: str, fields: Mapping[str, Any]) -> None:
        """Sets where the connection's calls go (base URL, credential name, api-version, region); a moved endpoint has
        not answered yet, so the observed region is cleared."""
        async with self.install_tx(CONNECTIONS, tables=(t,)) as c:
            await c.execute(t.update().where(t.c.id == provider_id).values(**fields, observed_region=None))

    async def observe(self, provider_id: str, region: str) -> None:
        """Records the region the provider answered from, when it differs from the one recorded."""
        async with self.install_tx(CONNECTIONS, tables=(t,)) as c:
            await c.execute(
                t.update()
                .where(t.c.id == provider_id, sa.or_(t.c.observed_region.is_(None), t.c.observed_region != region))
                .values(observed_region=region)
            )

    async def ensure(self, row: Mapping[str, Any]) -> None:
        """Adds the connection unless one with its id exists, which is left as it is."""
        async with self.install_tx(CONNECTIONS, tables=(t,)) as c:
            await c.execute(insert_ignore(c, t, row, keys=["id"]))

    async def follow_url(self, provider_id: str, base_url: str) -> None:
        """Points the connection at `base_url` unless it names a credential: one bound to a real provider keeps it."""
        async with self.install_tx(CONNECTIONS, tables=(t,)) as c:
            await c.execute(t.update().where(t.c.id == provider_id, t.c.key_ref.is_(None)).values(base_url=base_url))
