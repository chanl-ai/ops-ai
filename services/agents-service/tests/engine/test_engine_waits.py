"""engine_waits (c-525), on the migrated test database under the tenant role, by failure mode: a parked step that an
event cannot find (the row written apart from the run's waiting state); another team's event finding a step; a wait
row that outlives its resume, so a later event for the same key wakes nothing or the wrong thing; a cancelled run
parked again."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import DefinitionStore, RunStore
from ops_service_kit.ids import new_id
from ops_store.team_scope import acting_as

FLOW = parse(
    {
        "schemaVersion": 2,
        "id": "waits_flow",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "done"}},
        ],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }
)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def _run(tx: EngineTransactions, team: str) -> str:
    version, _ = await DefinitionStore(tx).publish(
        FLOW.id, name="Waits", definition=FLOW.wire(), digest=FLOW.digest(), now="n", by="a@x", stage="live", team=team
    )
    run_id = new_id("wfrun")
    await RunStore(tx).create(
        {"id": run_id, "team_id": team, "workflow_id": FLOW.id, "version": version, "digest": FLOW.digest()}
        | {"run_key": run_id, "mode": "live", "input": {}, "created_by": "a@x"}
    )
    return run_id


def _waiting(interrupt: str = "int_1") -> dict[str, object]:
    return {"node": "read", "iteration": 1, "interruptId": interrupt, "payload": {"kind": "external"}}


async def test_a_parked_step_is_found_by_its_event_in_its_team_only_and_a_resume_clears_it(engine: AsyncEngine) -> None:
    tenant, key = f"t-{uuid4().hex[:8]}", f"ext_{uuid4().hex[:8]}"
    tx = EngineTransactions(engine)
    runs = RunStore(tx)
    with tenant_scope(tenant), acting_as("team_ops"):
        run_id = await _run(tx, "team_ops")
        await runs.park(run_id, generation=None, waiting=_waiting(), wait={"event": "extraction.finished", "key": key})
        run = await runs.get(run_id) or {}
        found = await runs.waits_for("extraction.finished", key)
    with tenant_scope(tenant), acting_as("team_fraud"):
        theirs = await runs.waits_for("extraction.finished", key)
    with tenant_scope(tenant), acting_as("team_ops"):
        cleared = await runs.unpark(run_id, "read", 1)
        after = await runs.waits_for("extraction.finished", key)
        again = await runs.unpark(run_id, "read", 1)
    assert run["status"] == "waiting" and run["waiting"]["interruptId"] == "int_1", run
    assert [(w["run_id"], w["team_id"], w["interrupt_id"]) for w in found] == [(run_id, "team_ops", "int_1")], found
    assert theirs == [], "another team's event finds no step of this team"
    assert cleared and after == [] and not again


async def test_parking_the_same_step_again_keeps_one_row_for_the_new_pause(engine: AsyncEngine) -> None:
    tenant, key = f"t-{uuid4().hex[:8]}", f"ext_{uuid4().hex[:8]}"
    tx = EngineTransactions(engine)
    runs = RunStore(tx)
    with tenant_scope(tenant), acting_as("team_ops"):
        run_id = await _run(tx, "team_ops")
        await runs.park(
            run_id, generation=None, waiting=_waiting("int_1"), wait={"event": "extraction.finished", "key": key}
        )
        await runs.park(
            run_id, generation=None, waiting=_waiting("int_2"), wait={"event": "extraction.finished", "key": key}
        )
        found = await runs.waits_for("extraction.finished", key)
    assert [w["interrupt_id"] for w in found] == ["int_2"], found


async def test_a_cancelled_run_is_not_parked(engine: AsyncEngine) -> None:
    tenant, key = f"t-{uuid4().hex[:8]}", f"ext_{uuid4().hex[:8]}"
    tx = EngineTransactions(engine)
    runs = RunStore(tx)
    with tenant_scope(tenant), acting_as("team_ops"):
        run_id = await _run(tx, "team_ops")
        await runs.cancel(run_id)
        await runs.park(run_id, generation=None, waiting=_waiting(), wait={"event": "extraction.finished", "key": key})
        run = await runs.get(run_id) or {}
        found = await runs.waits_for("extraction.finished", key)
    assert run["status"] == "cancelled" and found == [], (run["status"], found)
