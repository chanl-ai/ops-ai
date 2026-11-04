"""A tool operation's mock answers at rest: rows per operation and environment, in order, one the default.

Keyed by the module and the operation's name: a name is unique within a module, not across teams' modules. The
"example" environment holds the operation's example answer, which ModuleStore reads as the operation's `stub`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import Guarantee

from .modules import operation_mocks

Row = dict[str, Any]


class MockStore:
    # Clearing the old default and setting a new one land together.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    @staticmethod
    def _of(tenant_id: str, module_id: str, operation: str, environment: str) -> tuple[Any, ...]:
        # By module and operation name: names repeat across teams' modules since tools are per team, and a
        # mock answers only the operation it was made on.
        m = operation_mocks.c
        return (
            m.tenant_id == tenant_id,
            m.module_id == module_id,
            m.operation == operation,
            m.environment == environment,
        )

    async def listed(self, tenant_id: str, module_id: str, operation: str, environment: str) -> list[Row]:
        """An operation's mocks in order; an operation holds a handful, so all are read."""
        q = (
            operation_mocks.select()
            .where(*self._of(tenant_id, module_id, operation, environment))
            .order_by(operation_mocks.c.position, operation_mocks.c.id)
        )
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def get(self, tenant_id: str, mock_id: str) -> Row | None:
        q = operation_mocks.select().where(operation_mocks.c.tenant_id == tenant_id, operation_mocks.c.id == mock_id)
        async with self.engine.connect() as c:
            row = (await c.execute(q)).mappings().first()
            return dict(row) if row else None

    async def add(self, row: Row) -> None:
        """Appends the mock after the operation's others; a new default clears the old one in the same transaction."""
        async with self.engine.begin() as c:
            where = self._of(row["tenant_id"], row["module_id"], row["operation"], row["environment"])
            last = (await c.execute(sa.select(sa.func.max(operation_mocks.c.position)).where(*where))).scalar()
            if row["is_default"]:
                await c.execute(operation_mocks.update().where(*where).values(is_default=False))
            await c.execute(operation_mocks.insert().values(**row, position=int(last or 0) + 1))

    async def change(self, tenant_id: str, mock_id: str, values: Row, *, at: datetime) -> Row | None:
        async with self.engine.begin() as c:
            key = (operation_mocks.c.tenant_id == tenant_id, operation_mocks.c.id == mock_id)
            row = (await c.execute(operation_mocks.select().where(*key))).mappings().first()
            if row is None:
                return None
            if values.get("is_default"):
                where = self._of(tenant_id, row["module_id"], row["operation"], row["environment"])
                await c.execute(operation_mocks.update().where(*where).values(is_default=False))
            await c.execute(operation_mocks.update().where(*key).values(**values, updated_at=at))
            return {**dict(row), **values, "updated_at": at}

    async def delete(self, tenant_id: str, mock_id: str) -> bool:
        q = operation_mocks.delete().where(operation_mocks.c.tenant_id == tenant_id, operation_mocks.c.id == mock_id)
        async with self.engine.begin() as c:
            return (await c.execute(q)).rowcount > 0
