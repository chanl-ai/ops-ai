"""A review step's notDecidedBy (c-257 asks it of c-258's engine): a person it names may not decide the review whatever
their role, such as whoever saved the tool module version it approves; anyone else decides as before. On PostgreSQL
with the real worker; failure mode: the named person approves their own change."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api import engine_reviews
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import DefinitionStore, RunStore
from ops_service_kit.errors import Forbidden
from ops_service_kit.ids import new_id
from tests.engine.test_worker import CountingTools, M, drain, worker

FLOW = parse(
    {
        "schemaVersion": 2,
        "id": "module_security_review",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {
                "id": "review",
                "type": "ops.flow.humanReview",
                "typeVersion": 1,
                "parameters": {"title": "Approve the module", "notDecidedBy": "$.input.savedBy"},
            },
            {"id": "ok", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "approved"}},
            {"id": "no", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "rejected"}},
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "review", "port": "in"}},
            {"from": {"node": "review", "port": "approve"}, "to": {"node": "ok", "port": "in"}},
            {"from": {"node": "review", "port": "reject"}, "to": {"node": "no", "port": "in"}},
        ],
    }
)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_a_person_the_step_names_cannot_decide_and_another_reviewer_can(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    tx = EngineTransactions(engine)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            FLOW.id, name="Module review", definition=FLOW.wire(), digest=FLOW.digest(), now="n", by="a@x", stage="live"
        )
        run_id = new_id("wfrun")
        run = {"id": run_id, "team_id": "team_a", "workflow_id": FLOW.id, "version": version, "digest": FLOW.digest()}
        # The saver's address as the module recorded it, in another case: the match ignores case.
        await RunStore(tx).create(
            run | {"run_key": run_id, "mode": "live", "input": {"savedBy": "M@X"}, "created_by": "a@x"}
        )
    w = worker(engine, CountingTools(), InMemorySaver())
    await drain(w)
    rt: Any = SimpleNamespace(db=engine, settings=SimpleNamespace(lease_ttl_seconds=6.0))
    with tenant_scope(tenant), pytest.raises(Forbidden) as refused:
        await engine_reviews.decide(rt, M, run_id, decision="approved", reason=None)
    assert refused.value.code == "not_decided_by"
    with tenant_scope(tenant):
        await engine_reviews.decide(rt, replace(M, name="n@x", email="n@x"), run_id, decision="approved", reason=None)
    await drain(w)
    with tenant_scope(tenant):
        ended = await RunStore(tx).get(run_id) or {}
    assert (ended["status"], ended["outcome"]) == ("succeeded", "approved"), ended


async def test_whoever_the_step_names_as_asking_decides_while_the_requester_policy_is_on(engine: AsyncEngine) -> None:
    """requestedBy follows requesterMayDecide (tick 29): while it is on, the default, the asker decides."""
    asked = parse(
        {
            **FLOW.wire(),
            "id": "access_asked",
            "nodes": [
                n
                if n["id"] != "review"
                else {**n, "parameters": {"title": "Grant access", "requestedBy": "$.input.asker"}}
                for n in FLOW.wire()["nodes"]
            ],
        }
    )
    tenant = f"t-{uuid4().hex[:8]}"
    tx = EngineTransactions(engine)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            asked.id, name="Access", definition=asked.wire(), digest=asked.digest(), now="n", by="a@x", stage="live"
        )
        run_id = new_id("wfrun")
        run = {"id": run_id, "team_id": "team_a", "workflow_id": asked.id, "version": version, "digest": asked.digest()}
        await RunStore(tx).create(
            run | {"run_key": run_id, "mode": "live", "input": {"asker": "M@X"}, "created_by": "event:tools/x"}
        )
    w = worker(engine, CountingTools(), InMemorySaver())
    await drain(w)
    rt: Any = SimpleNamespace(db=engine, settings=SimpleNamespace(lease_ttl_seconds=6.0))
    with tenant_scope(tenant):
        await engine_reviews.decide(rt, M, run_id, decision="approved", reason=None)
    await drain(w)
    with tenant_scope(tenant):
        assert ((await RunStore(tx).get(run_id)) or {}).get("outcome") == "approved"
