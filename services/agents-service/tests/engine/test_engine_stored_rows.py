"""The engine's run, step and definition rows read as models, on the migrated test database, by failure mode: the
definition read back hashes to another digest; the waiting state read and written back changes; a row stored before a
newer column was filled (no node type, no started_via) fails to read, or the mapping agents-service reads differs from
the stored row."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import DefinitionStore, RunStore
from ops_engine.store.tables import engine_runs, engine_steps
from ops_service_kit.ids import new_id
from ops_store.team_scope import acting_as
from tests.run_rows import write_run

FLOW = parse(
    {
        "schemaVersion": 2,
        "id": "rows_flow",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "done", "note": "é"}},
        ],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }
)
# Key order, a float, a null and non-ASCII text: what a dump that rebuilt the state would change.
WAITING = {
    "node": "read",
    "iteration": 2,
    "interruptId": "int_9",
    "payload": {"kind": "external", "zeta": 1.5, "alpha": None, "title": "Revisión", "list": [3, {"b": 1, "a": 2}]},
}


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def _run(tx: EngineTransactions) -> tuple[str, int]:
    version, _ = await DefinitionStore(tx).publish(
        FLOW.id, name="Rows", definition=FLOW.wire(), digest=FLOW.digest(), now="n", by="a@x", stage="live", team="t1"
    )
    run_id = new_id("wfrun")
    await write_run(
        tx,
        {"id": run_id, "team_id": "t1", "workflow_id": FLOW.id, "version": version, "digest": FLOW.digest()}
        | {"run_key": run_id, "mode": "live", "input": {"n": 1}, "created_by": "a@x"},
    )
    return run_id, version


def _same(a: object, b: object) -> bool:
    return json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False)


async def test_a_stored_definition_reads_back_to_the_same_digest(engine: AsyncEngine) -> None:
    tx = EngineTransactions(engine)
    with tenant_scope(f"t-{uuid4().hex[:8]}"), acting_as("t1"):
        _, version = await _run(tx)
        row = await DefinitionStore(tx).row(FLOW.id, version)
        mapping = await DefinitionStore(tx).get(FLOW.id, version)
    assert row is not None and mapping is not None
    assert row.digest == FLOW.digest() and parse(cast(dict[str, Any], row.definition)).digest() == FLOW.digest()
    assert _same(row.definition, FLOW.wire()) and _same(mapping["definition"], FLOW.wire())


async def test_the_waiting_state_read_and_written_back_is_unchanged(engine: AsyncEngine) -> None:
    tx = EngineTransactions(engine)
    runs = RunStore(tx)
    with tenant_scope(f"t-{uuid4().hex[:8]}"), acting_as("t1"):
        run_id, _ = await _run(tx)
        await runs.park(run_id, generation=None, waiting=WAITING)
        first = await runs.row(run_id)
        assert first is not None
        await runs.update(run_id, waiting=first.waiting)
        again = await runs.row(run_id)
        mapping = await runs.get(run_id)
    assert again is not None and mapping is not None
    assert _same(first.waiting, WAITING) and _same(again.waiting, WAITING) and _same(mapping["waiting"], WAITING)


async def test_an_older_row_reads_and_the_mapping_is_the_stored_row(engine: AsyncEngine) -> None:
    tx = EngineTransactions(engine)
    runs = RunStore(tx)
    with tenant_scope(f"t-{uuid4().hex[:8]}"), acting_as("t1"):
        run_id, _ = await _run(tx)
        async with tx.tenant_tx() as c:
            # A step journaled before node types were kept (agents migration 0058).
            step = {"run_id": run_id, "node_id": "start", "iteration": 1, "attempt": 1, "tenant_id": tx.tenant()}
            at = {"status": "succeeded", "effects": "none", "key": f"{run_id}:start:1:1", "started_at": "2026-01-01"}
            await c.execute(engine_steps.insert().values(**step, **at))
            stored = dict((await c.execute(sa.select(engine_runs).where(engine_runs.c.id == run_id))).mappings().one())
        steps = await runs.step_rows(run_id)
        mapping = await runs.get(run_id)
    assert [(s.node_id, s.node_type, s.port) for s in steps] == [("start", None, None)], steps
    assert mapping is not None and stored["started_via"] is None
    assert mapping == stored and list(mapping) == list(stored)


async def test_a_definition_stored_as_null_or_a_list_still_lists_as_an_empty_definition(engine: AsyncEngine) -> None:
    tx = EngineTransactions(engine)
    store = DefinitionStore(tx)
    odd = {f"rows_null_{uuid4().hex[:6]}": None, f"rows_list_{uuid4().hex[:6]}": [1, 2]}
    with tenant_scope(f"t-{uuid4().hex[:8]}"), acting_as("t1"):
        for wid, stored in odd.items():
            await store.publish(
                wid, name=wid, definition=cast(Any, stored), digest=wid.ljust(64, "0"), now="n", by="a@x",
                stage="live", team="t1",
            )  # fmt: skip
        listed = {s.workflow_id: s.definition for s in await store.summaries(team="t1")}
        live = {d.workflow_id: d.definition for d in await store.live_everywhere() if d.workflow_id in odd}
    empty: dict[str, object] = {w: {} for w in odd}
    assert {w: listed.get(w) for w in odd} == empty, listed
    assert live == empty, live
