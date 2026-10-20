"""Reviews older than typed steps draw through a task type (tick 31's design check), on PostgreSQL with the real worker,
by failure mode: an old review of a workflow whose live step now names a type keeps the old layout, or loses the run's
values; a plain approve or reject review has no task; a review with its own options is forced into approve and reject;
a mapped task cannot be decided."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api import engine_reviews, legacy_tasks
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_agents.task_types import seeds
from ops_engine.store import DefinitionStore, RunStore
from tests.engine.review_flows import flow, paused
from tests.engine.test_worker import M, drain

UNTYPED = flow({"title": "Open the case for Marcus Bell?"})
TYPED = flow(
    {
        "title": "Open the case",
        "taskType": {"id": "generic_decision"},
        "params": {
            "title": "Open the case for {$.input.name}?",
            "facts": [{"label": "Amount", "value": "$.input.amount"}],
        },
    }
)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def _task(rt: Any, tenant: str, run_id: str) -> dict[str, Any] | None:
    with tenant_scope(tenant):
        return (await engine_reviews.get(rt, run_id)).get("task")


async def test_an_old_review_draws_with_the_type_its_workflow_now_names(engine: AsyncEngine) -> None:
    tenant, run_id, rt, _ = await paused(engine, UNTYPED)
    with tenant_scope(tenant):
        store = DefinitionStore(EngineTransactions(engine))
        version, _ = await store.publish(
            TYPED.id, name="Case check", definition=TYPED.wire(), digest=TYPED.digest(), now="n", by="a@x"
        )
        await store.go_live(TYPED.id, version)
    task = await _task(rt, tenant, run_id)
    assert task is not None and task["type"]["id"] == "generic_decision", task
    regions = {r["region"]: r["data"] for r in task["regions"]}
    assert regions["header"] == {"title": "Open the case for Marcus Bell?"}, regions
    assert regions["facts"]["facts"] == [{"label": "Amount", "value": "3,250.00"}], regions


async def test_a_plain_old_review_draws_as_a_general_decision(engine: AsyncEngine) -> None:
    tenant, run_id, rt, w = await paused(engine, UNTYPED)
    task = await _task(rt, tenant, run_id)
    assert task is not None and task["type"]["id"] == "generic_decision", task
    assert [a["port"] for a in task["actions"]] == ["approve", "reject"]
    with tenant_scope(tenant):
        await engine_reviews.decide(rt, M, run_id, decision="approve", reason=None)
    await drain(w)
    with tenant_scope(tenant):
        assert ((await RunStore(EngineTransactions(engine)).get(run_id)) or {}).get("outcome") == "approved"


async def test_a_review_with_its_own_options_keeps_them(engine: AsyncEngine) -> None:
    escalating = flow({"title": "Handle it", "options": [{"name": "approve"}, {"name": "escalate"}]})
    tenant, run_id, rt, _ = await paused(engine, escalating)
    assert await _task(rt, tenant, run_id) is None


async def test_an_old_read_check_draws_as_a_document_check(engine: AsyncEngine) -> None:
    """Round 4: wfrun_48b7b17251c6's check holds its read as records under the summary's `read`, and drew as a general
    decision with no key fields."""
    read = {
        "fileId": "fil_letter",
        "schema": [{"key": "name", "label": "Debtor", "keyField": True}, {"key": "amount", "label": "Amount"}],
        "records": [{"values": {"name": "Marcus Bell", "amount": "3,250.00"}}],
    }
    check = flow(
        {"title": "Check the read", "summary": {"read": read, "document": "letter.pdf"}, "editable": "$.input"}
    )
    tenant, run_id, rt, _ = await paused(engine, check)
    task = await _task(rt, tenant, run_id)
    assert task is not None and task["type"]["id"] == "document_check", task
    regions = {r["region"]: r["data"] for r in task["regions"]}
    assert regions["document"]["file"] == "fil_letter", regions


def test_every_type_an_old_review_draws_with_is_seeded() -> None:
    """A type map naming a type no tenant has would draw every such old review as a missing type."""
    seeded = {str(t["id"]) for t in seeds()}
    assert set(legacy_tasks.legacy_types().values()) <= seeded, legacy_tasks.legacy_types()
    assert set(legacy_tasks.legacy_types()) == {"read", "reply", "write", "decision"}
