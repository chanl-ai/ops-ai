"""Bank aliases and their immutable versions. A change is a new version, and the newest one not retired serves."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, ClassVar, NotRequired, TypedDict

import sqlalchemy as sa

from ops_service_kit.http import ListResult, Out
from ops_service_kit.ids import now_iso
from ops_service_kit.listing import ListParams
from ops_store import Guarantee, isolation
from ops_store.dialect import locked
from ops_store.listing import list_page
from ops_store.rows import one
from ops_store.store import Store

from .provider_keys import ROLE
from .providers import callers, mine
from .tables import model_aliases as t
from .tables import provider_connections as p

SENSITIVITY = ("public", "internal", "confidential", "restricted")


def cleared(alias_ceiling: str, data: str) -> bool:
    """Whether an alias cleared up to `alias_ceiling` may receive data of class `data`; an unknown class never is."""
    if alias_ceiling not in SENSITIVITY or data not in SENSITIVITY:
        return False
    return SENSITIVITY.index(data) <= SENSITIVITY.index(alias_ceiling)


class AliasFields(TypedDict):
    """What an alias version names beyond its alias: where its calls go, the data it may carry and its prices. A field
    left out takes the column's default."""

    provider_id: str
    model_id: str
    cleared_sensitivity: str
    input_per_million: Decimal
    output_per_million: Decimal
    reasoning_effort: NotRequired[str | None]
    images: NotRequired[bool]


class AliasRow(Out):
    """One version of an alias, as stored."""

    name: str
    version: int
    kind: str
    provider_id: str
    model_id: str
    cleared_sensitivity: str
    input_per_million: Decimal
    output_per_million: Decimal
    status: str
    created_at: str
    reasoning_effort: str | None
    images: bool


class ServingAlias(AliasRow):
    """The version serving an alias, with where its connection's calls go and the name of the key they sign in with."""

    type: str
    base_url: str | None
    key_ref: str | None
    api_version: str | None
    region: str | None
    observed_region: str | None


# Every column but the tenant, which a row never shows: it is always the caller's.
SHOWN = tuple(c for c in t.c if c.name != "tenant_id")


def ours() -> sa.ColumnElement[bool]:
    """The caller's account's alias versions."""
    return callers(t.c.tenant_id)


# The serving version of each of the caller's account's aliases, joined to its connection. One version is current per
# alias (ux_model_aliases_current), so a name selects at most one row.
SERVING = (
    sa.select(*SHOWN, p.c.type, p.c.base_url, p.c.key_ref, p.c.api_version, p.c.region, p.c.observed_region)
    .join(p, sa.and_(p.c.id == t.c.provider_id, mine()))
    .where(ours(), t.c.status == "current")
)


class Aliases(Store):
    # Each alias is an account's: every statement runs in the caller's tenant as ROLE, which the database holds to that
    # tenant's aliases and connections (models 20261128_0015).
    role = ROLE
    # A new version locks the alias's newest row, retires the serving one and inserts the next in one transaction; the
    # primary key (name, version) refuses a second writer's equal number (TRANSACTION, CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.CAS})

    async def _bindable(self, c: Any, provider_id: str) -> bool:
        """Whether a version may be bound to `provider_id`: a connection of the caller's account."""
        return bool(await c.scalar(sa.select(p.c.id).where(mine(), p.c.id == provider_id)))

    async def current(self, name: str) -> ServingAlias | None:
        """The version serving `name`, with its connection's type, base URL, key name, api-version and regions."""
        async with self.tx() as c:
            q = SERVING.where(t.c.name == name).order_by(t.c.version.desc()).limit(1)
            return await one(c, q, ServingAlias)

    async def page(self, params: ListParams) -> ListResult[ServingAlias]:
        """One page of the aliases' serving versions by name; `search` matches the name, the kind or the model, and
        `ids` names aliases by name."""
        query, params = _named(SERVING, t.c.name, params)
        async with self.tx() as c:
            page = await list_page(
                c, query, params, search=(t.c.name, t.c.kind, t.c.model_id), default_sort=t.c.name.asc()
            )
        return ListResult[ServingAlias].model_validate(page)

    async def version_page(self, name: str, params: ListParams) -> ListResult[AliasRow] | None:
        """One page of `name`'s versions, oldest first; `search` matches the model or the status, and `ids` names
        versions by number. None when there is no such alias, so an alias whose versions match nothing is told apart
        from one that does not exist."""
        query, params = _named(sa.select(*SHOWN).where(ours(), t.c.name == name), t.c.version, params, numbers=True)
        async with self.tx() as c:
            page = await list_page(c, query, params, search=(t.c.model_id, t.c.status), default_sort=t.c.version.asc())
            # Asked only when nothing matched, so a listed alias costs no statement more.
            held = sa.select(t.c.name).where(ours(), t.c.name == name).limit(1)
            if page["pagination"]["total"] == 0 and not await c.scalar(held):
                return None
        return ListResult[AliasRow].model_validate(page)

    async def create(self, name: str, kind: str, fields: AliasFields) -> bool | None:
        """Version 1 of a new alias; False, and nothing written, when the alias exists; None when the connection is not
        one of the caller's account's."""
        async with self.tx() as c:
            if not await self._bindable(c, fields["provider_id"]):
                return None
            if (await c.execute(sa.select(t.c.name).where(ours(), t.c.name == name))).first():
                return False
            await c.execute(t.insert().values(**fields, **_current(name, 1, kind)))
        return True

    async def add_version(self, name: str, fields: AliasFields) -> int | None:
        """The next version of `name`, which replaces the one serving; None when there is no such alias, or the
        connection is not one of the caller's account's."""
        async with self.tx() as c:
            if not await self._bindable(c, fields["provider_id"]):
                return None
            newest = sa.select(*SHOWN).where(ours(), t.c.name == name).order_by(t.c.version.desc()).limit(1)
            last = await one(c, locked(newest, t), AliasRow)
            if last is None:
                return None
            version = last.version + 1
            # One version of an alias is current at a time (ux_model_aliases_current), so the old one is retired in
            # this transaction.
            current = sa.and_(ours(), t.c.name == name, t.c.status == "current")
            await c.execute(t.update().where(current).values(status="retired"))
            await c.execute(t.insert().values(**fields, **_current(name, version, last.kind)))
        return version


def _named(
    query: sa.Select[Any], column: sa.Column[Any], params: ListParams, *, numbers: bool = False
) -> tuple[sa.Select[Any], ListParams]:
    """`ids` narrowed here, by `column`: an alias version is keyed by (name, version), and list_page picks ids only by
    a key of one column. The rows ids name are answered whatever the search says, as list_page answers them."""
    if params.ids is None:
        return query, params
    wanted: list[Any] = [int(i) for i in params.ids if i.isdigit()] if numbers else list(params.ids)
    return query.where(column.in_(wanted)), params.model_copy(update={"ids": None, "search": None})


class _Current(TypedDict):
    tenant_id: str
    name: str
    version: int
    kind: str
    status: str
    created_at: str


def _current(name: str, version: int, kind: str) -> _Current:
    return {
        "tenant_id": isolation.tenant(),
        "name": name,
        "version": version,
        "kind": kind,
        "status": "current",
        "created_at": now_iso(),
    }
