"""Provider connections: where an alias version's calls go, and the name of the credential they use (never the
credential itself). Each is an account's: every read and write runs in the caller's tenant as ROLE, which the database
holds to that tenant's rows (models_0014), so another account's connection is a connection that does not exist."""

from __future__ import annotations

from typing import ClassVar, NotRequired, TypedDict

import sqlalchemy as sa

from ops_service_kit.http import ListResult, Out
from ops_service_kit.listing import ListParams
from ops_store import Guarantee, isolation
from ops_store.dialect import insert_ignore
from ops_store.listing import list_page
from ops_store.rows import one
from ops_store.store import Store

from .provider_keys import ROLE
from .tables import provider_connections as t

# Every column but the tenant, which a row never shows: it is always the caller's.
SHOWN = tuple(c for c in t.c if c.name != "tenant_id")


def callers(column: sa.Column[str]) -> sa.ColumnElement[bool]:
    """`column` is the caller's tenant, named in each statement as well as held by the policy, so a login that bypasses
    row security (a database owner, SQL Server before its predicates land) still reads one account's rows."""
    # Bound when the statement runs, so a module-level query (aliases.SERVING) reads the tenant of the call it serves.
    return column == sa.bindparam(None, type_=sa.String(64), callable_=isolation.tenant)


def mine() -> sa.ColumnElement[bool]:
    """The caller's account's connections."""
    return callers(t.c.tenant_id)


class NewProvider(TypedDict):
    """The columns of a connection row when it is added."""

    id: str
    name: str
    type: str
    base_url: str | None
    key_ref: str | None
    api_version: NotRequired[str | None]
    region: NotRequired[str | None]
    created_at: str


class ProviderBinding(TypedDict):
    """Where a connection's calls go."""

    base_url: str | None
    key_ref: str | None
    api_version: str | None
    region: str | None


class InstallConnection(ProviderBinding):
    """The install's settings' connection: it also names the type, which wins over the stored one."""

    type: str


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
    role = ROLE
    # A connection's name is unique in its account, so two creates of one name cannot both land (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    async def page(
        self, params: ListParams, *, name: str | None = None, key_ref: str | None = None
    ) -> ListResult[ProviderRow]:
        """One page of the connections by name, then id; `search` matches the name or the type, `ids` names
        connections by id. `name` and `key_ref` keep only the connection of that name or those that sign in with
        that key."""
        given = {"name": name, "key_ref": key_ref}
        query = sa.select(*SHOWN).where(
            mine(), *(t.c[column] == value for column, value in given.items() if value is not None)
        )
        async with self.tx() as c:
            page = await list_page(
                c,
                query,
                params,
                search=(t.c.name, t.c.type),
                sortable={"name": t.c.name, "type": t.c.type},
                default_sort=t.c.name.asc(),
            )
        return ListResult[ProviderRow].model_validate(page)

    async def get(self, provider_id: str) -> ProviderRow | None:
        async with self.tx() as c:
            return await one(c, sa.select(*SHOWN).where(mine(), t.c.id == provider_id), ProviderRow)

    async def create(self, row: NewProvider) -> bool:
        """Adds a connection; False, and nothing written, when one with the same name exists."""
        async with self.tx() as c:
            if (await c.execute(sa.select(t.c.id).where(mine(), t.c.name == row["name"]))).first():
                return False
            await c.execute(t.insert().values(**row, tenant_id=isolation.tenant()))
        return True

    async def rebind(self, provider_id: str, fields: ProviderBinding) -> None:
        """Sets where the connection's calls go (base URL, credential name, api-version, region); a moved endpoint has
        not answered yet, so the observed region is cleared."""
        async with self.tx() as c:
            await c.execute(t.update().where(mine(), t.c.id == provider_id).values(**fields, observed_region=None))

    async def observe(self, provider_id: str, region: str) -> None:
        """Records the region the provider answered from, when it differs from the one recorded."""
        async with self.tx() as c:
            await c.execute(
                t.update()
                .where(
                    mine(), t.c.id == provider_id, sa.or_(t.c.observed_region.is_(None), t.c.observed_region != region)
                )
                .values(observed_region=region)
            )

    async def ensure(self, row: NewProvider) -> None:
        """Adds the connection unless one with its id exists, which is left as it is."""
        async with self.tx() as c:
            await c.execute(insert_ignore(c, t, {**row, "tenant_id": isolation.tenant()}, keys=["id"]))

    async def follow_url(self, provider_id: str, base_url: str) -> None:
        """Points the connection at `base_url` unless it names a credential: one bound to a real provider keeps it."""
        async with self.tx() as c:
            await c.execute(
                t.update().where(mine(), t.c.id == provider_id, t.c.key_ref.is_(None)).values(base_url=base_url)
            )
