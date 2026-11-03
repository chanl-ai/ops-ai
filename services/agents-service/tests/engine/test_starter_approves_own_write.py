"""A workflow step approving a write is decided as the starter's own when they may approve it, on PostgreSQL with the
real worker, by failure mode: a run started by an approver still waits for a person; a
run started by someone who may not approve skips the person; and a write two people approve, or one that asks for a
step-up, skips them."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.engine_host import RunEvents, RunReviews, StarterApprovals, ThreadLeases
from ops_agents.api.worker import enter_run
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.events import EventLog
from ops_agents.store.leases import Leases
from ops_agents.store.reviews import ReviewStore
from ops_agents.store.tenancy import tenant_scope
from ops_engine import default_registry
from ops_engine.definition import parse
from ops_engine.ports import EnginePorts
from ops_engine.store import DefinitionStore, RunStore
from ops_engine.worker import Worker, WorkerHost
from ops_service_kit.ids import new_id
from tests.engine.test_worker import CountingTools, drain

NOTE = parse(
    {
        "schemaVersion": 2,
        "id": "case_note_own",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {
                "id": "review",
                "type": "ops.flow.humanReview",
                "typeVersion": 1,
                "parameters": {"title": "Write the note", "approves": "note"},
            },
            {
                "id": "note",
                "type": "ops.action.tool",
                "typeVersion": 1,
                "parameters": {
                    "operation": "add_customer_note",
                    "input": {"text": "$.input.name"},
                    "approvedBy": "review",
                },
            },
            {"id": "ok", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "noted"}},
            {"id": "no", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "rejected"}},
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "review", "port": "in"}},
            {"from": {"node": "review", "port": "approve"}, "to": {"node": "note", "port": "in"}},
            {"from": {"node": "review", "port": "reject"}, "to": {"node": "no", "port": "in"}},
            {"from": {"node": "note", "port": "ok"}, "to": {"node": "ok", "port": "in"}},
        ],
    }
)


class _Gateway:
    """tools-service's answer for the write's approval policy."""

    def __init__(self, approval: dict[str, Any]) -> None:
        self.approval = approval

    async def tool_policy(self, tool: str) -> dict[str, Any]:
        return {"name": tool, "access": "write", "approval": self.approval}


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


def _worker(engine: AsyncEngine, tools: CountingTools, approval: dict[str, Any]) -> Worker:
    owner = f"test-{uuid4().hex[:6]}"
    starters = StarterApprovals(engine, _Gateway(approval))  # pyright: ignore[reportArgumentType]
    host = WorkerHost(
        tx=EngineTransactions(engine),
        registry=default_registry(),
        ports=EnginePorts(tools=tools, reviews=RunReviews(starters=starters)),
        leases=ThreadLeases(Leases(engine, owner=owner, ttl=6.0)),
        events=RunEvents(EventLog(engine)),
        checkpointer=InMemorySaver(),
        run_scope=tenant_scope,
        owner=owner,
        enter_run=enter_run,
    )
    return Worker(host)


async def _run(engine: AsyncEngine, *, approver: bool, approval: dict[str, Any]) -> tuple[dict[str, Any], int, str]:
    """Starts a run as an approver or not, drains the worker; the run, how many tool calls went out, its tenant."""
    tenant, tx, tools = f"t-{uuid4().hex[:8]}", EngineTransactions(engine), CountingTools()
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            NOTE.id, name="Note", definition=NOTE.wire(), digest=NOTE.digest(), now="n", by="a@x", stage="live"
        )
        run_id = new_id("wfrun")
        await RunStore(tx).create(
            {
                "id": run_id,
                "team_id": "team_a",
                "workflow_id": NOTE.id,
                "version": version,
                "digest": NOTE.digest(),
                "run_key": run_id,
                "mode": "live",
                "input": {"name": "Called back"},
                "created_by": "priya@harborpine.example",
                "started_by_approver": approver,
            }
        )
    await drain(_worker(engine, tools, approval))
    with tenant_scope(tenant):
        run = await RunStore(tx).get(run_id) or {}
    return run, len(tools.calls), tenant


async def test_an_approvers_run_writes_without_waiting_and_the_approval_is_theirs(engine: AsyncEngine) -> None:
    run, sent, tenant = await _run(engine, approver=True, approval={"approvers": 1})
    assert (run["status"], run.get("outcome"), sent) == ("succeeded", "noted", 1), run
    with tenant_scope(tenant):
        approvers = await ReviewStore(engine).approvers(str(run["id"]), f"{run['id']}:note:1:1")
    assert approvers == ["priya@harborpine.example"], approvers


async def test_a_run_started_by_someone_who_may_not_approve_waits(engine: AsyncEngine) -> None:
    run, sent, _ = await _run(engine, approver=False, approval={"approvers": 1})
    assert (run["status"], run["waiting"]["node"], sent) == ("waiting", "review", 0), run


@pytest.mark.parametrize("approval", [{"approvers": 2}, {"approvers": 1, "stepUp": True}])
async def test_a_write_two_people_or_a_step_up_approve_still_waits(
    engine: AsyncEngine, approval: dict[str, Any]
) -> None:
    run, sent, _ = await _run(engine, approver=True, approval=approval)
    assert (run["status"], sent) == ("waiting", 0), run
