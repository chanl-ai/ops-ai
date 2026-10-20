"""Masking where people read a run (c-321, tick 31: mask what people see, keep workflow data real), on PostgreSQL with
the real worker, by failure mode: the run page shows a step's email or SSN with the setting on; it masks with the team's
setting off; the stored run carries the masked value, so a later Send step would send to "[email]"."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.routers.engine import RunsQuery, cancel_engine_run, get_engine_run, list_engine_runs
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import DefinitionStore, RunStore
from ops_service_kit.ids import new_id
from tests.engine.test_worker import CountingTools, M, drain, worker

FLOW = parse(
    {
        "schemaVersion": 2,
        "id": "notify_customer",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "sent"}},
        ],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }
)
GIVEN = {"email": "ann.lee@example.com", "note": "SSN 123-45-6789"}


class Policies:
    def __init__(self, mask: Any) -> None:
        self.mask = mask

    async def value(self, key: str) -> Any:
        return self.mask if key == "aiStepsMaskPersonalData" else {}


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def _ran(engine: AsyncEngine, flow: Any = FLOW, by: str = "a@x") -> tuple[str, str]:
    tenant, tx = f"t-{uuid4().hex[:8]}", EngineTransactions(engine)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            flow.id, name="Notify", definition=flow.wire(), digest=flow.digest(), now="n", by="a@x", stage="live"
        )
        run_id = new_id("wfrun")
        run = {"id": run_id, "team_id": "team_a", "workflow_id": flow.id, "version": version, "digest": flow.digest()}
        await RunStore(tx).create(run | {"run_key": run_id, "mode": "live", "input": GIVEN, "created_by": by})
    await drain(worker(engine, CountingTools(), InMemorySaver()))
    return tenant, run_id


async def _read(engine: AsyncEngine, tenant: str, run_id: str, mask: Any) -> dict[str, Any]:
    rt: Any = SimpleNamespace(db=engine, policies=Policies(mask), settings=SimpleNamespace(review_sla_hours=24.0))
    with tenant_scope(tenant):
        return json.loads(bytes((await get_engine_run(rt, M, run_id)).body))["data"]


async def test_the_run_page_masks_what_the_stored_run_keeps_real(engine: AsyncEngine) -> None:
    tenant, run_id = await _ran(engine)
    shown = json.dumps(await _read(engine, tenant, run_id, {}))
    assert "ann.lee@example.com" not in shown and "123-45-6789" not in shown and "[email]" in shown, shown
    with tenant_scope(tenant):
        stored = await RunStore(EngineTransactions(engine)).steps(run_id)
    assert "ann.lee@example.com" in json.dumps(stored, default=str)


async def test_a_team_that_turned_masking_off_reads_real_values(engine: AsyncEngine) -> None:
    tenant, run_id = await _ran(engine)
    assert "ann.lee@example.com" in json.dumps(await _read(engine, tenant, run_id, {"team_a": False}))


async def test_every_read_of_a_waiting_run_masks_what_it_shows(engine: AsyncEngine) -> None:
    """tick 32: the runs list and cancel answered unmasked, and so did a waiting step's payload on every read."""
    waiting = parse(
        {
            "schemaVersion": 2,
            "id": "call_back",
            "nodes": [
                {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
                {
                    "id": "review",
                    "type": "ops.flow.humanReview",
                    "typeVersion": 1,
                    "parameters": {"title": "Write to {$.input.email}?"},
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
    tenant, run_id = await _ran(engine, waiting, by=M.email)
    rt: Any = SimpleNamespace(db=engine, policies=Policies({}), settings=SimpleNamespace(review_sla_hours=24.0))
    with tenant_scope(tenant):
        listed = json.loads(bytes((await list_engine_runs(rt, M, RunsQuery())).body))["data"]
        cancelled = json.loads(bytes((await cancel_engine_run(rt, M, run_id)).body))["data"]
    detail = await _read(engine, tenant, run_id, {})
    for shown in (listed, cancelled, detail):
        assert "ann.lee@example.com" not in json.dumps(shown), json.dumps(shown)[:400]
    assert "[email]" in json.dumps(detail["waiting"] or cancelled), detail["waiting"]
