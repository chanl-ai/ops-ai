"""A tool operation's mock answers at rest (c-332): rows per operation and environment, in order, one the default.

Keyed by the operation's name, which is unique in a tenant and is what the gateway resolves a call by; `module_id` is
the module that held the operation when the mock was made, for the module's pages.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import Guarantee

from .modules import metadata

_TS = sa.DateTime(timezone=True)

operation_mocks = sa.Table(
    "operation_mocks",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("module_id", sa.String(64), nullable=False),
    sa.Column("operation", sa.String(120), nullable=False),
    # test only for now: production never reads a mock.
    sa.Column("environment", sa.String(16), nullable=False),
    # Order within the operation's mocks: the first whose match holds answers.
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    # Input field to the value it must equal; empty matches every call.
    sa.Column("match", sa.JSON, nullable=False),
    sa.Column("status", sa.Integer, nullable=False),
    sa.Column("body", sa.JSON),
    sa.Column("headers", sa.JSON, nullable=False),
    sa.Column("delay_ms", sa.Integer, nullable=False),
    # Answers nothing within the operation's time limit: the call fails UPSTREAM_TIMEOUT as a real one would.
    sa.Column("timeout", sa.Boolean, nullable=False),
    # The one a call gets when no other matches; at most one per operation and environment, kept by the service.
    sa.Column("is_default", sa.Boolean, nullable=False),
    # The logged call it was saved from, when it was.
    sa.Column("from_call_id", sa.String(64)),
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", _TS, nullable=False),
    sa.Column("updated_at", _TS, nullable=False),
    sa.Index("ix_operation_mocks_operation", "tenant_id", "operation", "environment", "position"),
)

Row = dict[str, Any]


class MockStore:
    # Clearing the old default and setting a new one land together.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    @staticmethod
    def _of(tenant_id: str, operation: str, environment: str) -> tuple[Any, ...]:
        m = operation_mocks.c
        return (m.tenant_id == tenant_id, m.operation == operation, m.environment == environment)

    async def listed(self, tenant_id: str, operation: str, environment: str) -> list[Row]:
        """An operation's mocks in order; an operation holds a handful, so all are read."""
        q = (
            operation_mocks.select()
            .where(*self._of(tenant_id, operation, environment))
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
            where = self._of(row["tenant_id"], row["operation"], row["environment"])
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
                where = self._of(tenant_id, row["operation"], row["environment"])
                await c.execute(operation_mocks.update().where(*where).values(is_default=False))
            await c.execute(operation_mocks.update().where(*key).values(**values, updated_at=at))
            return {**dict(row), **values, "updated_at": at}

    async def delete(self, tenant_id: str, mock_id: str) -> bool:
        q = operation_mocks.delete().where(operation_mocks.c.tenant_id == tenant_id, operation_mocks.c.id == mock_id)
        async with self.engine.begin() as c:
            return (await c.execute(q)).rowcount > 0
