"""A thread's budget and its model-call ledger are held to the thread's tenant by the database (migration 0104), with
raw SQL and no WHERE clause as ops_runtime_tenant, by failure mode: a tenant reading or writing another tenant's budget
or recorded model response; a row written past the store with no tenant reaching every tenant; and the ledger's store
methods reading a thread's calls without a tenant. On the PostgreSQL test database migrated to head."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.model_calls import ModelCall, ModelCallLedger, model_call_records
from ops_agents.store.tenancy import TENANT_ROLE, NoTenantError, tenant_scope
from ops_agents.store.usage import thread_budgets
from ops_service_kit.ids import new_id
from ops_store.conformance import isolation_suite
from ops_store.schema import isolation_kind

TABLES = (thread_budgets, model_call_records)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


def _call(thread_id: str) -> ModelCall:
    return ModelCall(thread_id, None, "step", "model", "chat", 1, 1, 1, 1)


def _thread(_tenant: str, _team: str | None) -> dict[str, Any]:
    return {"thread_id": new_id("gth")}


async def test_each_runtime_table_holds_a_tenant_to_its_rows(engine: AsyncEngine) -> None:
    assert [isolation_kind(t) for t in TABLES] == ["tenant", "tenant"]
    fill = {t.name: _thread for t in TABLES}
    assert await isolation_suite(engine, TABLES, role=TENANT_ROLE, fill=fill) == []


async def test_the_ledger_records_under_the_callers_tenant_and_another_tenant_sees_none(engine: AsyncEngine) -> None:
    ledger, thread = ModelCallLedger(engine), new_id("gth")
    mine, other = f"t_{new_id('x')}", f"t_{new_id('x')}"
    with pytest.raises(NoTenantError):
        await ledger.record(_call(thread))
    with tenant_scope(mine):
        assert await ledger.record(_call(thread))
        assert len(await ledger.calls(thread)) == 1
    with tenant_scope(other):
        assert await ledger.calls(thread) == []
    async with engine.begin() as c:
        tenants = (
            await c.execute(sa.select(model_call_records.c.tenant_id).where(model_call_records.c.thread_id == thread))
        ).scalars()
        assert list(tenants) == [mine]
        await c.execute(model_call_records.delete().where(model_call_records.c.thread_id == thread))
