"""What a discovery found in a source, kept for 24 hours so the add-module picker pages and searches it in SQL.

POST /v1/tool-modules/discover reads a source (an OpenAPI document or an MCP server) and stores one `tool_discoveries`
row, its meta, and one `tool_discovery_operations` row per operation it found. An operation is stored with only the
fields the console sees (name, description, access, method, path, group, input): the call's headers, body and example
answer stay out, so no secret reference or upstream answer is at rest here. Import reads the source again, as it
always has, so nothing here decides what a module calls.

A discovery belongs to the person who asked (`person`) in their team, and to the module it was made for (`module_id`,
none for a new module). A read past `expires_at` finds nothing whether or not it was deleted; storing a new discovery
deletes the team's expired ones in the same transaction, so no background loop is needed. The tables are held to
their team by the database (tools migration 20261122_2022_discoveries), so a request's sweep reaches its own team's
rows, and another team's expired rows go when that team next discovers.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, ClassVar, TypedDict

import sqlalchemy as sa
from pydantic import JsonValue

from ops_service_kit.listing import ListParams
from ops_store import Guarantee
from ops_store.listing import LISTED, ListPage, Rows, list_page, listed_rows
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.store import Store
from ops_store.team_scope import team_visible

from .modules import metadata, module_operations
from .tenancy import ROLE

tool_discoveries = sa.Table(
    "tool_discoveries",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    # The person who asked (the principal's subject): only they read it back.
    sa.Column("person", sa.String(128), nullable=False),
    # The module the operations are being added to; none while a new module is drafted.
    sa.Column("module_id", sa.String(64)),
    # The source's meta as the console shows it: type, system, suggestedName, version, endpoint, warnings, noAuth.
    sa.Column("meta", sa.JSON, nullable=False),
    sa.Column("operation_total", sa.Integer, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    # The sweep on each new discovery deletes the team's rows past their expiry.
    sa.Index("ix_tool_discoveries_expires", "tenant_id", "team_id", "expires_at"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

tool_discovery_operations = sa.Table(
    "tool_discovery_operations",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("discovery_id", sa.String(64), primary_key=True),
    # The source's order, which the picker lists them in.
    sa.Column("position", sa.Integer, primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("name", sa.String(120), nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("access", sa.String(16), nullable=False, info=LISTED),
    sa.Column("method", sa.String(8)),
    sa.Column("path", sa.Text),
    # The operation's resource group (`group` is a reserved word on both databases).
    sa.Column("op_group", sa.String(200), nullable=False, info=LISTED),
    sa.Column("input", sa.JSON, nullable=False),
    sa.ForeignKeyConstraint(
        ["tenant_id", "discovery_id"], ["tool_discoveries.tenant_id", "tool_discoveries.id"], ondelete="CASCADE"
    ),
    # "Already added" and the select-all names match a discovery's operations to a module's by name.
    sa.Index("ix_tool_discovery_operations_name", "tenant_id", "discovery_id", "name"),
    # The picker's two filters, each read within one discovery.
    sa.Index("ix_tool_discovery_operations_access", "tenant_id", "team_id", "access", "discovery_id"),
    sa.Index("ix_tool_discovery_operations_group", "tenant_id", "team_id", "op_group", "discovery_id"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


class FoundOperation(TypedDict):
    """One operation as the console sees it: what is stored, nothing more."""

    name: str
    description: str
    access: str
    method: str | None
    path: str | None
    group: str
    input: list[Any]


class DiscoveryRow(TypedDict):
    id: str
    module_id: str | None
    meta: dict[str, JsonValue]
    operation_total: int


class NameRow(TypedDict):
    name: str
    access: str


_d, _o = tool_discoveries.c, tool_discovery_operations.c
# The page's columns, under the console's names; `added` is set per row by `operations`.
_COLUMNS = (
    _o.name,
    _o.description,
    _o.access,
    _o.method,
    _o.path,
    _o.op_group.label("group"),
    _o.input,
)
SEARCH = (_o.name, _o.description, _o.path)
FILTERS = {"group": _o.op_group, "access": _o.access}


def _on_module(module_id: str | None) -> sa.ColumnElement[bool]:
    """The operation's name is already on the module: an EXISTS on the module's operations, so no name is bound."""
    if module_id is None:
        return sa.false()
    m = module_operations.c
    return sa.exists().where(m.tenant_id == _o.tenant_id, m.module_id == module_id, m.name == _o.name)


class Discoveries(Store):
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})
    role = ROLE

    async def save(
        self,
        *,
        tenant_id: str,
        team_id: str,
        id: str,
        person: str,
        module_id: str | None,
        meta: dict[str, JsonValue],
        operations: Sequence[FoundOperation],
        now: datetime,
        expires_at: datetime,
    ) -> None:
        """Stores one discovery and its operations, after deleting the team's discoveries past their expiry."""
        expired = sa.select(_d.id).where(
            _d.tenant_id == tenant_id, _d.expires_at <= now, team_visible(tool_discoveries)
        )
        rows = [
            {"tenant_id": tenant_id, "discovery_id": id, "position": i, "team_id": team_id, "name": o["name"],
             "description": o["description"], "access": o["access"], "method": o["method"], "path": o["path"],
             "op_group": o["group"], "input": o["input"]}
            for i, o in enumerate(operations)
        ]  # fmt: skip
        async with self.tx() as c:
            gone = [r[0] for r in await c.execute(expired)]
            if gone:
                # The children first: SQLite in the tests does not cascade without its foreign-key pragma.
                await c.execute(
                    tool_discovery_operations.delete().where(
                        _o.tenant_id == tenant_id, _o.discovery_id.in_(gone), team_visible(tool_discovery_operations)
                    )
                )
                await c.execute(
                    tool_discoveries.delete().where(
                        _d.tenant_id == tenant_id, _d.id.in_(gone), team_visible(tool_discoveries)
                    )
                )
            await c.execute(
                tool_discoveries.insert().values(
                    tenant_id=tenant_id, id=id, team_id=team_id, person=person, module_id=module_id, meta=meta,
                    operation_total=len(rows), created_at=now, expires_at=expires_at,
                )
            )  # fmt: skip
            if rows:
                await c.execute(tool_discovery_operations.insert(), rows)

    async def find(self, tenant_id: str, id: str, *, team_id: str, person: str, now: datetime) -> DiscoveryRow | None:
        """The discovery, when `person` made it in `team_id` and it has not expired. The team is named as well as
        `team_visible`: a caller that reads every team (the dev header caller) still reads only its own team's."""
        q = sa.select(_d.id, _d.module_id, _d.meta, _d.operation_total).where(
            _d.tenant_id == tenant_id,
            _d.id == id,
            _d.team_id == team_id,
            _d.person == person,
            _d.expires_at > now,
            team_visible(tool_discoveries),
        )
        async with self.tx() as c:
            row = (await c.execute(q)).mappings().first()
        return None if row is None else DiscoveryRow(**row)  # type: ignore[typeddict-item]

    def _of(self, tenant_id: str, found: DiscoveryRow, *columns: Any) -> Rows:
        return sa.select(*columns).where(
            _o.tenant_id == tenant_id, _o.discovery_id == found["id"], team_visible(tool_discovery_operations)
        )

    async def operations(self, tenant_id: str, found: DiscoveryRow, q: ListParams) -> tuple[ListPage[Any], int]:
        """One page of the discovery's operations, searched on name, description and path, with `group` and `access`
        filters and facets; each row says whether the module already has it (`added`). Also answers how many of the
        matching operations the module already has."""
        on_module = _on_module(found["module_id"])
        added = sa.case((on_module, 1), else_=0).label("added")
        async with self.tx() as c:
            page = await list_page(
                c,
                self._of(tenant_id, found, *_COLUMNS, added),
                q,
                search=SEARCH,
                default_sort=_o.position.asc(),
                filters=FILTERS,
                facets=FILTERS,
            )
            counting = self._of(tenant_id, found, sa.func.count()).where(on_module)
            already = int((await c.execute(listed_rows(counting, q, search=SEARCH, filters=FILTERS))).scalar_one())
        for row in page["data"]:
            row["added"] = bool(row["added"])
        return page, already

    async def names(self, tenant_id: str, found: DiscoveryRow, q: ListParams) -> list[NameRow]:
        """Every matching operation the module does not have yet, by name and its access as found, in the source's
        order: bounded by the discovery's own size."""
        query = self._of(tenant_id, found, _o.name, _o.access).where(sa.not_(_on_module(found["module_id"])))
        async with self.tx() as c:
            rows = await c.execute(listed_rows(query, q, search=SEARCH, filters=FILTERS).order_by(_o.position))
            return [NameRow(name=r.name, access=r.access) for r in rows]
