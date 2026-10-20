"""Who a Human Task is assigned to is read in the caller's tenant only (c-074): with no row-level security (SQLite),
another tenant's assignment of the same review id would otherwise show as this tenant's assignee."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.store.base import metadata
from ops_agents.store.review_assignments import ReviewAssignments
from ops_agents.store.tenancy import tenant_scope


async def test_an_assignment_in_another_tenant_is_not_this_tenants() -> None:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    store = ReviewAssignments(engine)
    with tenant_scope("tenant_a"):
        await store.assign("TMP-1", "maya@a.example", by="maya@a.example")
    with tenant_scope("tenant_b"):
        await store.assign("TMP-1", "omar@b.example", by="omar@b.example")
        assert await store.current() == {"TMP-1": "omar@b.example"}
    with tenant_scope("tenant_a"):
        assert await store.current() == {"TMP-1": "maya@a.example"}
