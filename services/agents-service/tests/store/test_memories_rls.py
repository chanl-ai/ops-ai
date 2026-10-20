"""Agent memories on PostgreSQL, by failure mode: the retention sweep cannot list the tenants holding memories. It
lists them as the role that bypasses row-level security (Memories.tenants), which 0048 never granted the table, so on
the shared stack every pass logged "permission denied for table agent_memories" and no memory ever expired. Runs on
the migrated test database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.memories import Memories, agent_memories
from ops_agents.store.tenancy import system_tx, tenant_scope


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_the_retention_sweep_lists_every_tenant_holding_a_memory(engine: AsyncEngine) -> None:
    if engine.dialect.name != "postgresql":
        pytest.skip("row-level security and roles are PostgreSQL's")
    tenants = [f"m-{uuid4().hex[:8]}" for _ in range(2)]
    store = Memories(engine)
    for tenant in tenants:
        with tenant_scope(tenant):
            await store.save(
                team_id="team_ops",
                agent_id="ag_x",
                person="p@x",
                kind="fact",
                key="branch",
                value="Leeds",
                confidence=1.0,
                source="said",
                thread_id=None,
            )
    assert set(tenants) <= set(await store.tenants())


async def test_the_bypass_role_reads_no_memory_values(engine: AsyncEngine) -> None:
    """The grant is the tenant column alone: the role that bypasses row-level security never reads what was saved."""
    if engine.dialect.name != "postgresql":
        pytest.skip("row-level security and roles are PostgreSQL's")
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with system_tx(engine, "test") as c:
            await c.execute(sa.select(agent_memories.c.value).limit(1))
