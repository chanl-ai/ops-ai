"""A typed decision carries what the reviewer gave (c-329), on PostgreSQL with the real worker, by failure mode: a
Reject's assignee is dropped, so the workflow cannot send the document to that person; an input the action does not
declare is taken silently; a correction is lost on the typed path."""

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


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


CHECK = flow(
    {
        "title": "Check the read",
        "taskType": {"id": "document_check"},
        "params": {"title": "Check what was read", "document": "fil_1", "fields": {}},
        "editable": "$.input",
    }
)


async def _review_output(engine: AsyncEngine, tenant: str, run_id: str) -> dict[str, Any]:
    with tenant_scope(tenant):
        steps = await RunStore(EngineTransactions(engine)).steps(run_id)
    return next(s["output"] for s in steps if s["node_id"] == "review" and s["status"] == "ok")


async def test_a_rejects_assignee_reaches_the_workflow(engine: AsyncEngine) -> None:
    tenant, run_id, rt, w = await paused(engine, CHECK)
    with tenant_scope(tenant):
        await engine_reviews.decide(
            rt, M, run_id, decision="reject", reason="Not a levy", inputs={"assignee": "m.okafor@northfieldbank.com"}
        )
    await drain(w)
    assert (await _review_output(engine, tenant, run_id))["inputs"] == {"assignee": "m.okafor@northfieldbank.com"}


async def test_an_input_the_action_does_not_declare_is_refused(engine: AsyncEngine) -> None:
    tenant, run_id, rt, _ = await paused(engine, CHECK)
    with tenant_scope(tenant), pytest.raises(ValidationFailed) as refused:
        await engine_reviews.decide(rt, M, run_id, decision="reject", reason="No", inputs={"asignee": "m@x"})
    assert "asignee" in str(refused.value)


async def test_a_correction_travels_with_a_typed_approval(engine: AsyncEngine) -> None:
    tenant, run_id, rt, w = await paused(engine, CHECK)
    with tenant_scope(tenant):
        await engine_reviews.decide(
            rt,
            M,
            run_id,
            decision="approve",
            reason=None,
            inputs={"edited": {"name": "Marcus J. Bell", "amount": "3,250.00"}},
        )
    await drain(w)
    assert (await _review_output(engine, tenant, run_id))["edited"]["name"] == "Marcus J. Bell"


async def test_a_person_input_that_is_not_an_email_is_refused(engine: AsyncEngine) -> None:
    """document_check's Reject sends the document to a person by email (format person); a name would leave the task
    with nobody."""
    tenant, run_id, rt, _ = await paused(engine, CHECK)
    with tenant_scope(tenant), pytest.raises(ValidationFailed) as refused:
        await engine_reviews.decide(rt, M, run_id, decision="reject", reason="No", inputs={"assignee": "Maya Okafor"})
    assert "assignee" in str(refused.value) and "email" in str(refused.value)
