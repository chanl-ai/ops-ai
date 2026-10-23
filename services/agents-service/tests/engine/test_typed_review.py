"""A workflow review step that names a task type (c-288), on PostgreSQL with the real worker and the review view, by
failure mode: publishing a new version of the type changes a task already open on the old one; a step naming no
version opens on no version, so its screen follows the type; the step's params reach the screen unresolved or
unbound; a missing required param hides the task instead of showing its fallback."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents import task_types as tt
from ops_agents.api import engine_reviews
from ops_agents.api.task_type_seeds import StoredTaskTypes, seeded_store
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import DefinitionStore, RunStore
from ops_service_kit.ids import new_id
from tests.engine.test_worker import CountingTools, drain, worker

FLOW = parse(
    {
        "schemaVersion": 2,
        "id": "vendor_bank_change",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {
                "id": "review",
                "type": "ops.flow.humanReview",
                "typeVersion": 1,
                "parameters": {
                    "title": "Bank change",
                    "taskType": {"id": "bank_change"},
                    "params": {"vendor": "$.input.vendor", "facts": "$.input.facts"},
                },
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


def _bank_change(question: str) -> dict[str, Any]:
    """A team's copy of write_approval whose header asks `question`, a template over the step's params."""
    seed = next(s for s in tt.seeds() if s["id"] == "write_approval")
    props = {**seed["params"]["properties"], "vendor": {"type": "string"}}
    regions = [{"region": "header", "bind": {"title": question}}, *seed["regions"][1:]]
    return {**seed, "name": "Bank change", "params": {**seed["params"], "properties": props}, "regions": regions}


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_an_open_task_keeps_its_version_when_the_type_moves_on(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    tx = EngineTransactions(engine)
    with tenant_scope(tenant):
        types = await seeded_store(engine, "team_a")
        await types.create(
            "bank_change",
            _bank_change("Change the bank account for {vendor}?"),
            team_id="team_a",
            by="b@x",
            copied_from=None,
        )
        await types.publish("bank_change", 1, by="b@x")
        version, _ = await DefinitionStore(tx).publish(
            FLOW.id, name="Bank change", definition=FLOW.wire(), digest=FLOW.digest(), now="n", by="a@x", stage="live"
        )
        run_id = new_id("wfrun")
        facts = [{"label": "New account", "value": "****4410"}]
        run = {"id": run_id, "team_id": "team_a", "workflow_id": FLOW.id, "version": version, "digest": FLOW.digest()}
        await RunStore(tx).create(
            run | {"run_key": run_id, "mode": "live", "input": {"vendor": "Acme", "facts": facts}, "created_by": "a@x"}
        )
    w = worker(engine, CountingTools(), InMemorySaver())
    w.host.ports.task_types = StoredTaskTypes(engine)
    await drain(w)
    rt: Any = SimpleNamespace(db=engine, settings=SimpleNamespace(lease_ttl_seconds=6.0, review_sla_hours=24.0))
    with tenant_scope(tenant):
        await types.save_draft("bank_change", _bank_change("Approve new bank details for {vendor}"), by="b@x")
        await types.publish("bank_change", 2, by="b@x")
        task = (await engine_reviews.get(rt, run_id))["task"]
    assert task["type"] == {"id": "bank_change", "version": 1, "name": "Bank change"}
    regions = {r["region"]: r["data"] for r in task["regions"]}
    assert regions["header"] == {"title": "Change the bank account for Acme?"}
    assert regions["facts"] == {"facts": facts}
    # The write itself was not passed: a warning, and its region is left out rather than drawn empty.
    assert "write_preview" not in regions
    assert [(x["field"], x["severity"]) for x in task["warnings"]] == [("title", "warning"), ("call", "warning")]
    assert [a["label"] for a in task["actions"]] == ["Make the change", "Decline"]
