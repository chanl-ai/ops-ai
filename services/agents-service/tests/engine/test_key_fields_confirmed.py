"""An action that waits for key fields (document_check's Approve, `requires: key_fields_confirmed`) is checked on the
server as the console checks it, on PostgreSQL with the real worker, by failure mode: a call that skips the console
approves values nobody checked; one record's confirmations pass for every record; a full confirmation is refused or
lost; Reject waits for key fields it does not need."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api import engine_reviews
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RunStore
from ops_service_kit.errors import ValidationFailed
from tests.engine.review_flows import flow, paused
from tests.engine.test_worker import M, drain

READ = {
    "fileId": "fil_1",
    "schema": [{"key": "name", "keyField": True}, {"key": "amount", "keyField": True}, {"key": "note"}],
    "records": [
        {"values": {"name": "Marcus Bell", "amount": "3,250.00", "note": ""}},
        {"values": {"name": "Ana Ruiz", "amount": "880.00", "note": ""}},
    ],
}
CHECK = flow(
    {
        "title": "Check the read",
        "taskType": {"id": "document_check"},
        "params": {"title": "Check what was read", "document": "fil_1", "fields": {}},
        "summary": {"read": READ},
    }
)
BOTH = {"0": ["name", "amount"], "1": ["amount", "name"]}


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def _outcome(engine: AsyncEngine, tenant: str, run_id: str) -> Any:
    with tenant_scope(tenant):
        run = await RunStore(EngineTransactions(engine)).get(run_id)
    return (run or {}).get("outcome")


async def test_an_approve_without_confirmations_is_refused(engine: AsyncEngine) -> None:
    tenant, run_id, rt, _ = await paused(engine, CHECK)
    with tenant_scope(tenant), pytest.raises(ValidationFailed) as refused:
        await engine_reviews.decide(rt, M, run_id, decision="approve", reason=None)
    assert refused.value.code == "key_fields_unconfirmed"
    assert "4 key fields" in str(refused.value)


async def test_one_records_confirmations_do_not_pass_for_another(engine: AsyncEngine) -> None:
    tenant, run_id, rt, _ = await paused(engine, CHECK)
    with tenant_scope(tenant), pytest.raises(ValidationFailed) as refused:
        await engine_reviews.decide(
            rt, M, run_id, decision="approve", reason=None, inputs={"confirmed": {"0": ["name", "amount"]}}
        )
    assert "2 key fields" in str(refused.value)


async def test_a_confirmed_approve_resumes_and_keeps_what_was_confirmed(engine: AsyncEngine) -> None:
    tenant, run_id, rt, w = await paused(engine, CHECK)
    with tenant_scope(tenant):
        await engine_reviews.decide(rt, M, run_id, decision="approve", reason=None, inputs={"confirmed": BOTH})
        decided = await engine_reviews._decisions(rt, run_id)  # pyright: ignore[reportPrivateUsage]
    assert decided[-1]["resume"]["confirmed"] == BOTH
    await drain(w)
    assert await _outcome(engine, tenant, run_id) == "approved"


async def test_a_reject_does_not_wait_for_key_fields(engine: AsyncEngine) -> None:
    tenant, run_id, rt, w = await paused(engine, CHECK)
    with tenant_scope(tenant):
        await engine_reviews.decide(rt, M, run_id, decision="reject", reason="Not a levy")
    await drain(w)
    assert await _outcome(engine, tenant, run_id) == "rejected"
