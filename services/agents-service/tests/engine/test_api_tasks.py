"""A task an API caller posts (c-288), through the route functions on PostgreSQL with the real worker, by failure mode:
the caller cannot read the decision a person made; a missing required value refuses the task instead of warning; a
value of the wrong kind is accepted and drawn as garbage; the task opens on whatever version is newest when someone
looks, not the one it was posted with."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api import engine_reviews
from ops_agents.api.event_workflows import EVENT_WORKFLOWS
from ops_agents.api.routers import tasks as tasks_route
from ops_agents.api.routers.tasks import TaskIn, create_task, get_task
from ops_agents.api.task_type_seeds import StoredTaskTypes
from ops_agents.store.tenancy import tenant_scope
from ops_service_kit.errors import Unprocessable
from tests.engine.test_worker import CountingTools, M, drain, worker

FACTS = [{"label": "Vendor", "value": "Acme"}, {"label": "New account", "value": "****4410"}]


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


def _data(res: Any) -> dict[str, Any]:
    return json.loads(bytes(res.body))["data"]


async def test_a_posted_task_is_decided_in_human_tasks_and_the_caller_reads_the_decision(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No worker runs until after the post, so the post answers `starting` after its wait; a short one keeps it quick.
    monkeypatch.setattr(tasks_route, "OPEN_WAIT_SECONDS", 0.3)
    tenant = f"t-{uuid4().hex[:8]}"
    rt: Any = SimpleNamespace(
        db=engine,
        event_workflows=EVENT_WORKFLOWS,
        event_workflows_seen=set(),
        settings=SimpleNamespace(lease_ttl_seconds=6.0, review_sla_hours=24.0),
    )
    body = TaskIn(type="generic_decision", params={"facts": FACTS, "onApprove": "The vendor's account is changed."})
    with tenant_scope(tenant):
        created = _data(await create_task(rt, M, body))
    assert (created["type"], created["version"], created["url"]) == ("generic_decision", 1, f"/reviews/{created['id']}")
    assert created["status"] == "starting"
    assert [(w["field"], w["severity"]) for w in created["warnings"]] == [("title", "warning")]

    w = worker(engine, CountingTools(), InMemorySaver())
    w.host.ports.task_types = StoredTaskTypes(engine)
    await drain(w)
    with tenant_scope(tenant):
        review = await engine_reviews.get(rt, created["id"])
        assert review["task"]["type"] == {"id": "generic_decision", "version": 1, "name": "Decision"}
        # The missing title shows the type's fallback line rather than hiding the task.
        assert review["task"]["regions"][0] == {"region": "header", "collapsed": False, "data": {"title": "Decision"}}
        assert _data(await get_task(rt, M, created["id"]))["action"] is None
        reviewer = replace(M, name="r@x", email="r@x")
        await engine_reviews.decide(rt, reviewer, created["id"], decision="rejected", reason="Call the vendor first")
    await drain(w)
    with tenant_scope(tenant):
        state = _data(await get_task(rt, M, created["id"]))
    assert (state["status"], state["action"], state["reason"], state["decidedBy"]) == (
        "rejected",
        "reject",
        "Call the vendor first",
        "r@x",
    ), state


async def test_a_value_of_the_wrong_kind_is_refused_naming_the_field(engine: AsyncEngine) -> None:
    rt: Any = SimpleNamespace(db=engine, event_workflows=EVENT_WORKFLOWS, event_workflows_seen=set())
    with tenant_scope(f"t-{uuid4().hex[:8]}"), pytest.raises(Unprocessable) as refused:
        await create_task(rt, M, TaskIn(type="generic_decision", params={"title": "Open it?", "facts": "Acme"}))
    assert refused.value.code == "invalid_task_params" and "facts" in str(refused.value)


async def test_a_retried_post_with_its_key_opens_one_task(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    """tick 30: a client retrying after a timeout opened a second task for one decision."""
    monkeypatch.setattr(tasks_route, "OPEN_WAIT_SECONDS", 0.1)
    rt: Any = SimpleNamespace(db=engine, event_workflows=EVENT_WORKFLOWS, event_workflows_seen=set())
    body = TaskIn(type="generic_decision", params={"title": "Open it?", "facts": FACTS})
    with tenant_scope(f"t-{uuid4().hex[:8]}"):
        first = _data(await create_task(rt, M, body, idempotency_key="order-77"))
        again = _data(await create_task(rt, M, body, idempotency_key="order-77"))
        other = _data(await create_task(rt, M, body, idempotency_key="order-78"))
    assert first["id"] == again["id"] != other["id"], (first, again, other)
