"""Engine rows are tenant rows: on PostgreSQL one tenant cannot read another's definitions, through the store or by
asking for the row outright (forced RLS from the migration, not a filter in a query)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope, tenant_tx
from ops_engine.store import DefinitionStore
from ops_engine.store.tables import engine_definitions


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_a_tenant_never_sees_another_tenants_definition(engine: AsyncEngine) -> None:
    a, b, wf = f"a-{uuid4().hex[:8]}", f"b-{uuid4().hex[:8]}", f"wf_{uuid4().hex[:8]}"
    store = DefinitionStore(EngineTransactions(engine))
    with tenant_scope(a):
        assert await store.publish(wf, name="W", definition={}, digest="d" * 64, now="now", by="x") == (1, True)
    with tenant_scope(b):
        assert await store.get(wf) is None
        async with tenant_tx(engine) as c:
            q = sa.select(sa.func.count()).select_from(engine_definitions).where(engine_definitions.c.workflow_id == wf)
            assert (await c.execute(q)).scalar_one() == 0
        # The same workflow id is b's own namespace: its first version is 1, not 2.
        assert await store.publish(wf, name="W", definition={}, digest="e" * 64, now="now", by="y") == (1, True)
