"""What people read when a step fails (c-446), on PostgreSQL with the real worker, read back through the run page's
route, by failure mode: the run's error is a Python exception (`ValueError: reply's input mailbox, subject is empty when
ack opens`, staging wfrun_ae6001c606ce), or the failed step is never marked failed and its detail is lost."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.routers.engine import get_engine_run
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.events import EventLog
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import DefinitionStore, RunStore
from ops_engine.store.tables import engine_work
from ops_engine.worker import MAX_PASSES
from ops_service_kit.ids import new_id
from tests.engine.test_worker import CountingTools, M, drain, worker

# A review that approves a reply, started with nothing to reply from: the reply's input reads nothing when it opens.
ACK = parse(
    {
        "schemaVersion": 2,
        "id": "acknowledge",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {
                "id": "ack",
                "type": "ops.flow.humanReview",
                "typeVersion": 1,
                "name": "Send the acknowledgement",
                "parameters": {"title": "Acknowledge", "approves": "reply"},
            },
            {
                "id": "reply",
                "type": "ops.action.tool",
                "typeVersion": 1,
                "name": "Reply from the mailbox",
                "parameters": {
                    "operation": "send_reply",
                    "approvedBy": "ack",
                    "input": {"to": "$.input.from", "mailbox": "$.input.mailbox"},
                },
            },
            {"id": "sent", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "replied"}},
            {"id": "not_sent", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "no_reply"}},
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "ack", "port": "in"}},
            {"from": {"node": "ack", "port": "approve"}, "to": {"node": "reply", "port": "in"}},
            {"from": {"node": "ack", "port": "reject"}, "to": {"node": "not_sent", "port": "in"}},
            {"from": {"node": "reply", "port": "ok"}, "to": {"node": "sent", "port": "in"}},
        ],
    }
)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


class NoPolicies:
    async def value(self, key: str) -> Any:
        return {}


async def test_a_failing_step_shows_people_a_plain_message_and_keeps_the_detail_on_the_step(
    engine: AsyncEngine,
) -> None:
    tenant, tx = f"t-{uuid4().hex[:8]}", EngineTransactions(engine)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            ACK.id, name="Acknowledge", definition=ACK.wire(), digest=ACK.digest(), now="n", by="a@x", stage="live"
        )
        run_id = new_id("wfrun")
        run = {"id": run_id, "team_id": "team_a", "workflow_id": ACK.id, "version": version, "digest": ACK.digest()}
        await RunStore(tx).create(
            run | {"run_key": run_id, "mode": "live", "input": {"from": "a@b.test"}, "created_by": "a@x"}
        )
    # The last pass the worker allows, so the run fails on this one instead of waiting out the retry backoff.
    async with engine.begin() as c:
        await c.execute(engine_work.update().where(engine_work.c.run_id == run_id).values(attempts=MAX_PASSES - 1))
    await drain(worker(engine, CountingTools(), InMemorySaver()))

    rt: Any = SimpleNamespace(db=engine, policies=NoPolicies(), settings=SimpleNamespace(review_sla_hours=24.0))
    with tenant_scope(tenant):
        shown = json.loads(bytes((await get_engine_run(rt, M, run_id)).body))["data"]
        events = await EventLog(engine).run_events(run_id, run_id, 0)
    assert shown["status"] == "failed", shown
    error = str(shown["error"])
    assert "Send the acknowledgement" in error and "mailbox" in error, error
    assert "Error" not in error and "ValueError" not in error, f"a Python exception reaches people: {error}"
    [step] = [s for s in shown["steps"] if s["nodeId"] == "ack"]
    assert step["status"] == "error" and "is empty when ack opens" in str(step["error"]), step
    [failed] = [e for e in events if e.get("type") == "failed" or e.get("event") == "failed"]
    data = cast(dict[str, Any], failed.get("data") or {})
    assert data.get("message") == error and "is empty when ack opens" in str(data.get("detail")), failed
