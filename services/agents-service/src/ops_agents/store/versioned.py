"""The reads the versioned registries (skills, guardrails, widgets) share: a record's row, the acting team's
rows, and its saved versions, each as the registry's row model through `ops_store.rows`. A subclass names its two
tables, the versions table's column naming the record, its row models and its noun; the writes stay its own.
"""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.errors import NotFound
from ops_service_kit.http import Out
from ops_store.dialect import locked
from ops_store.rows import Select, one
from ops_store.rows import rows as read_rows
from ops_store.team_scope import team_visible

from .tenancy import RuntimeStore, current_tenant


class VersionedRegistry[H: Out, V: Out](RuntimeStore):
    head: ClassVar[sa.Table]
    history: ClassVar[sa.Table]
    # The versions table's column naming the record a version belongs to.
    subject: ClassVar[str]
    noun: ClassVar[str]
    # The head columns `rows()` orders by.
    order: ClassVar[tuple[str, ...]] = ("id",)
    # Whether each read names the caller's tenant in the query as well as through the row policies (a table keyed by
    # tenant, where SQLite has no policy to apply).
    in_tenant: ClassVar[bool] = False
    head_row: type[H]
    version_row: type[V]

    def _scoped(self, table: sa.Table) -> list[sa.ColumnElement[bool]]:
        named = [table.c.tenant_id == current_tenant()] if self.in_tenant else []
        return [*named, team_visible(table)]

    async def _one[M: Out](self, q: Select, model: type[M], c: AsyncConnection | None) -> M | None:
        if c is not None:
            return await one(c, q, model)
        async with self.tx() as conn:
            return await one(conn, q, model)

    async def rows(self) -> list[H]:
        q = sa.select(self.head).where(*self._scoped(self.head)).order_by(*(self.head.c[k] for k in self.order))
        async with self.tx() as c:
            return await read_rows(c, q, self.head_row)

    async def find(self, record_id: str, c: AsyncConnection | None = None, *, lock: bool = False) -> H | None:
        q = sa.select(self.head).where(self.head.c.id == record_id, *self._scoped(self.head))
        return await self._one(locked(q, self.head) if lock else q, self.head_row, c)

    async def row(self, record_id: str, c: AsyncConnection | None = None, *, lock: bool = False) -> H:
        r = await self.find(record_id, c, lock=lock)
        if r is None:
            raise NotFound(f"{self.noun} {record_id}")
        return r

    def _versions_of(self, record_id: str) -> Select:
        v = self.history
        return sa.select(v).where(v.c[self.subject] == record_id, *self._scoped(v))

    async def versions(self, record_id: str) -> list[V]:
        q = self._versions_of(record_id).order_by(self.history.c.version.desc())
        async with self.tx() as c:
            return await read_rows(c, q, self.version_row)

    async def version(self, record_id: str, version: int, c: AsyncConnection | None = None) -> V | None:
        return await self._one(
            self._versions_of(record_id).where(self.history.c.version == version), self.version_row, c
        )

    async def newest(self, c: AsyncConnection, record_id: str, version: int) -> V:
        """The version a save edits or builds on, inside the saver's transaction; it exists, as the row names it."""
        found = await self.version(record_id, version, c)
        if found is None:
            raise NotFound(f"{self.noun} {record_id} version {version}")
        return found
