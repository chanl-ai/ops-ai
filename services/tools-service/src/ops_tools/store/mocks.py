"""A tool operation's mock answers at rest: rows per operation and environment, in order, one the default.

Keyed by the module and the operation's name: a name is unique within a module, not across teams' modules. The
"example" environment holds the operation's example answer, which ModuleStore reads as the operation's `stub`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, TypedDict

import sqlalchemy as sa
from pydantic import JsonValue, TypeAdapter

from ops_service_kit.listing import ListParams
from ops_store import Guarantee
from ops_store.listing import ListPage, list_page
from ops_store.store import Store

from .modules import operation_mocks
from .tenancy import ROLE


class MockChange(TypedDict, total=False):
    """The columns a change sets, only the ones it names."""

    name: str
    match: dict[str, JsonValue]
    status: int
    body: JsonValue
    headers: dict[str, str]
    delay_ms: int
    timeout: bool
    is_default: bool


class NewMock(TypedDict):
    """The columns of a mock to insert; its position is set after the operation's others."""

    tenant_id: str
    id: str
    module_id: str
    operation: str
    environment: str
    name: str
    match: dict[str, JsonValue]
    status: int
    body: JsonValue
    headers: dict[str, str]
    delay_ms: int
    timeout: bool
    is_default: bool
    from_call_id: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class MockRow(NewMock):
    """A stored mock: the insert's columns and its place in the operation's order."""

    position: int


# A row is checked against its columns as it leaves the store.
MOCK_ROW = TypeAdapter(MockRow)
MOCK_CHANGE = TypeAdapter(MockChange)


class MockStore(Store):
    # Clearing the old default and setting a new one land together.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})
    role = ROLE

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

    async def listed(self, tenant_id: str, module_id: str, operation: str, environment: str) -> list[MockRow]:
        """An operation's mocks in order; an operation holds a handful, so all are read."""
        q = (
            operation_mocks.select()
            .where(*self._of(tenant_id, module_id, operation, environment))
            .order_by(operation_mocks.c.position, operation_mocks.c.id)
        )
        async with self.tx() as c:
            return [MOCK_ROW.validate_python(dict(r)) for r in (await c.execute(q)).mappings()]

    async def page(
        self, tenant_id: str, module_id: str, operation: str, environment: str, params: ListParams
    ) -> ListPage:
        """One page of an operation's mocks in the order a test call checks them (position, then id), searched by
        name."""
        m = operation_mocks.c
        q = sa.select(*operation_mocks.c).where(*self._of(tenant_id, module_id, operation, environment))
        async with self.tx() as c:
            return await list_page(c, q, params, search=[m.name], sortable={"name": m.name}, default_sort=m.position)

    async def get(self, tenant_id: str, mock_id: str) -> MockRow | None:
        q = operation_mocks.select().where(operation_mocks.c.tenant_id == tenant_id, operation_mocks.c.id == mock_id)
        async with self.tx() as c:
            row = (await c.execute(q)).mappings().first()
            return MOCK_ROW.validate_python(dict(row)) if row else None

    async def add(self, row: NewMock) -> None:
        """Appends the mock after the operation's others; a new default clears the old one in the same transaction."""
        async with self.tx() as c:
            where = self._of(row["tenant_id"], row["module_id"], row["operation"], row["environment"])
            last = (await c.execute(sa.select(sa.func.max(operation_mocks.c.position)).where(*where))).scalar()
            if row["is_default"]:
                await c.execute(operation_mocks.update().where(*where).values(is_default=False))
            await c.execute(operation_mocks.insert().values(**row, position=int(last or 0) + 1))

    async def change(self, tenant_id: str, mock_id: str, values: MockChange, *, at: datetime) -> MockRow | None:
        async with self.tx() as c:
            key = (operation_mocks.c.tenant_id == tenant_id, operation_mocks.c.id == mock_id)
            row = (await c.execute(operation_mocks.select().where(*key))).mappings().first()
            if row is None:
                return None
            if values.get("is_default"):
                where = self._of(tenant_id, row["module_id"], row["operation"], row["environment"])
                await c.execute(operation_mocks.update().where(*where).values(is_default=False))
            await c.execute(operation_mocks.update().where(*key).values(**values, updated_at=at))
            return MOCK_ROW.validate_python({**dict(row), **values, "updated_at": at})

    async def delete(self, tenant_id: str, mock_id: str) -> bool:
        q = operation_mocks.delete().where(operation_mocks.c.tenant_id == tenant_id, operation_mocks.c.id == mock_id)
        async with self.tx() as c:
            return (await c.execute(q)).rowcount > 0
