"""Redrive of a Failed run through the worker on PostgreSQL, by failure mode: a redrive runs again a step that
completed or sends again a write that ran, and a redrive runs the workflow's latest version instead of the run's."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.ports import ToolResult
from ops_engine.store import DefinitionStore, RunStore
from tests.engine.test_worker import (
    BASIC,
    UncertainTools,
    drain,
    engine,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    start,
    worker,
)


class AnsweredTools(UncertainTools):
    """The write timed out at the caller but ran at the system: the gateway's record under its key says done."""

    async def find(self, key: str, operation: str) -> ToolResult | None:
        return ToolResult(True, {"id": "C-1"}) if key in self.calls else None


async def failed_run(db: AsyncEngine, tenant: str, tools: UncertainTools) -> str:
    run_id = await start(db, tenant, {"customerId": "C-1", "amount": 250})
    await drain(worker(db, tools, InMemorySaver()))
    with tenant_scope(tenant):
        run = await RunStore(EngineTransactions(db)).get(run_id) or {}
    assert run["status"] == "failed", run
    return run_id


async def test_a_redrive_reruns_no_completed_step_and_sends_no_write_twice(engine: AsyncEngine) -> None:  # noqa: F811
    tenant, tools = f"t-{uuid4().hex[:8]}", AnsweredTools()
    run_id = await failed_run(engine, tenant, tools)
    runs = RunStore(EngineTransactions(engine))
    with tenant_scope(tenant):
        _, changed = await runs.redrive(run_id)
    assert changed
    await drain(worker(engine, tools, InMemorySaver()))
    with tenant_scope(tenant):
        run = await runs.get(run_id) or {}
        steps = await runs.steps(run_id)
    waiting: dict[str, Any] = run["waiting"] or {}
    assert (run["status"], waiting.get("node")) == ("waiting", "review"), run
    assert [s["attempt"] for s in steps if s["node_id"] == "fields"] == [1], "a completed step ran again"
    assert [k for k in tools.calls if k.startswith(run_id)] == [f"{run_id}:lookup:1:1"], "the write was sent again"


async def test_a_redrive_runs_the_version_the_run_pinned_not_the_latest(engine: AsyncEngine) -> None:  # noqa: F811
    tenant, tools = f"t-{uuid4().hex[:8]}", AnsweredTools()
    run_id = await failed_run(engine, tenant, tools)
    # A later publish sends the lookup straight to an End: a run on it would succeed instead of waiting for review.
    later: dict[str, Any] = BASIC.wire()
    later["connections"] = [
        c if c["from"] != {"node": "lookup", "port": "ok"} else {**c, "to": {"node": "approved", "port": "in"}}
        for c in later["connections"]
    ]
    newer = parse(later)
    tx = EngineTransactions(engine)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            newer.id, name="Refund", definition=newer.wire(), digest=newer.digest(), now="now", by="a@x", stage="live"
        )
        assert version == 2
        await RunStore(tx).redrive(run_id)
    await drain(worker(engine, tools, InMemorySaver()))
    with tenant_scope(tenant):
        run = await RunStore(tx).get(run_id) or {}
    assert (run["status"], run["version"]) == ("waiting", 1), run
