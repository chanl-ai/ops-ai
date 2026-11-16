"""Who a Human Task is assigned to, by failure mode: read outside the caller's tenant (with no row-level security,
SQLite, another tenant's assignment of the same review id would show as this tenant's assignee); every assignment the
tenant ever made read to answer a few reviews; an earlier assignee answered after a reassignment, or ids split across
queries losing one."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.store import review_assignments
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
        assert await store.current(["TMP-1"]) == {"TMP-1": "omar@b.example"}
    with tenant_scope("tenant_a"):
        assert await store.current(["TMP-1"]) == {"TMP-1": "maya@a.example"}


async def test_only_the_asked_reviews_are_read_each_at_its_latest_assignee(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    # One id a query, so the asked ids span several queries.
    monkeypatch.setattr(review_assignments, "IDS_PER_QUERY", 1)
    store = ReviewAssignments(engine)
    with tenant_scope("tenant_a"):
        for review, who in [("R-1", "maya"), ("R-2", "omar"), ("R-1", "lina"), ("R-3", "sam")]:
            await store.assign(review, f"{who}@a.example", by="maya@a.example")
        assert await store.current(["R-2", "R-1", "R-9"]) == {"R-1": "lina@a.example", "R-2": "omar@a.example"}
        assert await store.current([]) == {}
