"""A workflow with one review step, run by the real worker to its pause: the review tests' shared setup."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.api.task_type_seeds import StoredTaskTypes
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import WorkflowDefinition, parse
from ops_engine.store import DefinitionStore, RunStore
from ops_service_kit.ids import new_id
from tests.engine.test_worker import CountingTools, drain, worker


def flow(review: dict[str, Any]) -> WorkflowDefinition:
    return parse(
        {
            "schemaVersion": 2,
            "id": "case_check",
            "nodes": [
                {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
                {"id": "review", "type": "ops.flow.humanReview", "typeVersion": 1, "parameters": review},
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


async def paused(engine: AsyncEngine, first: WorkflowDefinition) -> tuple[str, str, Any, Any]:
    """A run of `first` paused at its review, in a tenant of its own."""
    tenant, tx = f"t-{uuid4().hex[:8]}", EngineTransactions(engine)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            first.id, name="Case check", definition=first.wire(), digest=first.digest(), now="n", by="a@x", stage="live"
        )
        run_id = new_id("wfrun")
        run = {"id": run_id, "team_id": "team_a", "workflow_id": first.id, "version": version, "digest": first.digest()}
        given = {"name": "Marcus Bell", "amount": "3,250.00"}
        await RunStore(tx).create(run | {"run_key": run_id, "mode": "live", "input": given, "created_by": "a@x"})
    w = worker(engine, CountingTools(), InMemorySaver())
    w.host.ports.task_types = StoredTaskTypes(engine)
    await drain(w)
    rt: Any = SimpleNamespace(db=engine, settings=SimpleNamespace(lease_ttl_seconds=6.0, review_sla_hours=24.0))
    return tenant, run_id, rt, w
