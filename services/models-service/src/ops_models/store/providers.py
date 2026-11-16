"""Provider connections: where an alias version's calls go, and the name of the credential they use (never the
credential itself)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

import sqlalchemy as sa

from ops_service_kit.http import ListResult, Out
from ops_service_kit.listing import ListParams
from ops_store import Guarantee
from ops_store.dialect import insert_ignore
from ops_store.listing import list_page
from ops_store.rows import one
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

    async def page(
        self, params: ListParams, *, name: str | None = None, key_ref: str | None = None
    ) -> ListResult[ProviderRow]:
        """One page of the connections by name, then id; `search` matches the name or the type, `ids` names
        connections by id. `name` and `key_ref` keep only the connection of that name or those that sign in with
        that key."""
        given = {"name": name, "key_ref": key_ref}
        query = sa.select(t).where(*(t.c[column] == value for column, value in given.items() if value is not None))
        async with self.install_tx(CONNECTIONS, tables=(t,)) as c:
            page = await list_page(c, query, params, search=(t.c.name, t.c.type), default_sort=t.c.name.asc())
        return ListResult[ProviderRow].model_validate(page)

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
