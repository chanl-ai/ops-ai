"""Publish requests per tenant (c-333 phase A), on PostgreSQL with RLS, by failure mode: one tenant's pending request
blocks another's for the same subject (every tenant has the same seeded workflow ids); a tenant lists, reads or decides
another's requests; a statement with no tenant reads any."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from ops_agents.store import agent_registry
from ops_agents.store.agent_registry import AgentRegistry
from ops_agents.store.tenancy import NoTenantError, current_tenant, tenant_scope
from ops_service_kit.errors import NotFound


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


@asynccontextmanager
async def _no_rls(engine: AsyncEngine) -> AsyncGenerator[AsyncConnection]:
    """A transaction as a database without RLS gives it (SQL Server until c-349): nothing but the query's own filter."""
    current_tenant()
    async with engine.begin() as c:
        yield c


@pytest.mark.parametrize("rls", [True, False], ids=["rls", "query filter alone"])
async def test_each_tenant_has_its_own_requests(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, rls: bool
) -> None:
    if not rls:
        monkeypatch.setattr(agent_registry, "tenant_tx", _no_rls)
    reg = AgentRegistry(engine)
    a, b = f"t-{uuid4().hex[:8]}", f"t-{uuid4().hex[:8]}"
    subject = f"wf_{uuid4().hex[:6]}"
    opened: dict[str, dict[str, Any]] = {}
    for tenant in (a, b):
        with tenant_scope(tenant):
            opened[tenant] = await reg.open_request("workflow", subject, 2, note="", by="p@x", body={}, approved=False)
    with tenant_scope(a):
        mine = [r["id"] for r in await reg.all_requests()]
        assert mine == [opened[a]["id"]], mine
        assert [r["subject_id"] for r in await reg.requests("workflow", subject)] == [subject]
    with tenant_scope(b):
        # The same id in another tenant is another request: deciding b's leaves a's pending.
        assert await reg.decide_request(opened[b]["id"], "approved", "r@x", None)
    with tenant_scope(a):
        assert (await reg.request(opened[a]["id"]))["status"] == "pending"
    with tenant_scope(f"t-{uuid4().hex[:8]}"), pytest.raises(NotFound):
        await reg.request(opened[a]["id"])
    with pytest.raises(NoTenantError):
        await reg.all_requests()
