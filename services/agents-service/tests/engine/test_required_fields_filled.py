"""A read no model reply answered goes to a person to type, and the server holds approve until every required field
has a value, as the console holds the button, on PostgreSQL with the real worker, by failure mode: a call that skips
the console approves empty values; a typed value lost or an optional field blocking; a several-records read with no
records approved as zero records. The step names no task type, so the rule holds whatever type a workflow picks."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_access import BUILTIN_GRIDS, encode_grid
from ops_agents.api import engine_lifecycle, engine_reviews
from ops_agents.api.auth import Principal
from ops_agents.api.service_events import SEED, ensure_event_workflows
from ops_agents.api.task_type_seeds import StoredTaskTypes
from ops_agents.store.agent_registry import AgentRegistry
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import DefinitionStore, RunStore
from ops_identity import Principal as Caller
from ops_service_kit import narrow
from ops_service_kit.errors import Forbidden, ValidationFailed
from ops_service_kit.http import Json
from ops_service_kit.ids import new_id
from tests.engine.review_flows import flow, paused
from tests.engine.test_event_workflow_follow import Policies
from tests.engine.test_worker import CountingTools, M, drain, worker
from tests.run_rows import write_run

EVENT_SEED = Path(__file__).resolve().parents[2] / "seed" / "event_workflows.json"
SCHEMA = [
    {"key": "invoice", "label": "Invoice number", "type": "text", "required": True},
    {"key": "total", "label": "Total", "type": "money", "required": True},
    {"key": "po", "label": "PO number", "type": "text", "required": False},
]
NOT_READ_FIELD = {"value": None, "extractedValue": None, "confidence": 0.0, "needsReview": True, "notRead": "cut_off"}
ONE = {
    "fileId": "fil_88213",
    "incomplete": {"reason": "cut_off", "step": "extract:retry", "tries": 2},
    "schema": SCHEMA,
    "fields": {f["key"]: NOT_READ_FIELD for f in SCHEMA},
    "needsReview": [f["key"] for f in SCHEMA],
}
MANY = {
    "fileId": "fil_41",
    "incomplete": {"reason": "cut_off", "step": "extract", "tries": 1},
    "schema": SCHEMA,
    "records": [],
    "count": 0,
    "needsReview": [],
}


def _check(read: dict[str, Any]) -> Any:
    editable = read["records"] if "records" in read else read["fields"]
    return flow(
        {
            "title": "Type what was not read",
            "summary": {"document": "NWF-88213.pdf", "read": read},
            "editable": editable,
        }
    )


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def _outcome(engine: AsyncEngine, tenant: str, run_id: str) -> Any:
    with tenant_scope(tenant):
        run = await RunStore(EngineTransactions(engine)).get(run_id)
    return (run or {}).get("outcome")


async def test_approve_waits_for_every_required_field_and_keeps_what_was_typed(engine: AsyncEngine) -> None:
    tenant, run_id, rt, w = await paused(engine, _check(ONE))
    half: Json = {"invoice": {"value": "NWF-88213"}, "total": {"value": " "}}
    with tenant_scope(tenant):
        with pytest.raises(ValidationFailed) as empty:
            await engine_reviews.decide(rt, M, run_id, decision="approve", reason=None)
        with pytest.raises(ValidationFailed) as partly:
            await engine_reviews.decide(rt, M, run_id, decision="approve", reason=None, inputs={"edited": half})
        typed: Json = {"invoice": {"value": "NWF-88213"}, "total": {"value": "1,940.00"}}
        await engine_reviews.decide(rt, M, run_id, decision="approve", reason=None, inputs={"edited": typed})
        decided = await engine_reviews._decisions(rt, run_id)  # pyright: ignore[reportPrivateUsage]
    assert (empty.value.code, partly.value.code) == ("required_fields_empty", "required_fields_empty")
    assert "2 required fields" in str(empty.value) and "1 required field " in str(partly.value), partly.value
    # The optional PO number stays empty, and the typed values travel on the decision.
    assert narrow.an_object(decided[-1]["resume"], "the resume")["edited"] == typed
    await drain(w)
    assert await _outcome(engine, tenant, run_id) == "approved"


async def test_a_several_records_read_with_none_read_can_only_be_rejected(engine: AsyncEngine) -> None:
    tenant, run_id, rt, w = await paused(engine, _check(MANY))
    with tenant_scope(tenant):
        with pytest.raises(ValidationFailed) as refused:
            await engine_reviews.decide(rt, M, run_id, decision="approve", reason=None)
        await engine_reviews.decide(rt, M, run_id, decision="reject", reason="Read it again in parts")
    assert refused.value.code == "nothing_read", refused.value
    await drain(w)
    assert await _outcome(engine, tenant, run_id) == "rejected"


def _reviewer_without_documents_edit() -> Principal:
    """A reviewer of team_a whose role an admin took documents.edit off: decides tasks, changes no read's values."""
    grid = [g for g in BUILTIN_GRIDS["reviewer"] if (g[0], g[1]) != ("documents", "edit")]
    identity = Caller(
        kind="person",
        sub="usr_ines",
        email="ines@harborpine.example",
        name="Ines",
        tenant_id="local",
        team_id="team_a",
        team_ids=["team_a"],
        roles={"team_a": "reviewer"},
        scopes=[],
        auth_method="session",
        access={"team_a": ["reviewer"]},
        grids={"reviewer": encode_grid(grid)},
    )
    return Principal(
        name="Ines",
        email=identity.email,
        team_id="team_a",
        tenant_id="local",
        sub=identity.sub,
        team_ids=("team_a",),
        role="reviewer",
        roles={"team_a": "reviewer"},
        identity=identity,
    )


async def test_a_decider_without_documents_edit_changes_no_values_through_a_task(engine: AsyncEngine) -> None:
    tenant, run_id, rt, _ = await paused(engine, _check(ONE))
    typed: Json = {"invoice": {"value": "NWF-88213"}, "total": {"value": "1940"}}
    ines = _reviewer_without_documents_edit()
    with tenant_scope(tenant):
        with pytest.raises(Forbidden) as refused:
            await engine_reviews.decide(rt, ines, run_id, decision="approve", reason=None, inputs={"edited": typed})
        run = await RunStore(EngineTransactions(engine)).get(run_id)
    assert refused.value.code == "role_required", refused.value
    assert (run or {}).get("status") == "waiting", run


class NotRead:
    """documents-service answering the shipped Extract's read with no answer and keeping the typed values it is sent,
    files-service keeping its saves."""

    def __init__(self) -> None:
        self.saved: list[Json] = []
        self.corrected: list[tuple[str, list[Json], str]] = []

    async def extract(self, run_id: str, file_id: str, request: Json, *, key: str) -> Json:
        typed: Json = {"documentType": {"id": "freight_invoice", "version": 1, "name": "Freight invoice"}}
        answer: Json = {"id": "ext_88213", "status": "done", "outcome": "incomplete"}
        return answer | dict[str, Any](ONE) | typed

    async def correct(self, run_id: str, extraction_id: str, corrections: list[Json], *, entered_by: str) -> Json:
        self.corrected.append((extraction_id, corrections, entered_by))
        return {"id": extraction_id}

    async def set_data(self, run_id: str, file_id: str, data: Json) -> Json:
        self.saved.append(data)
        return {"data": data}


async def test_the_shipped_extract_waits_for_typed_required_fields_and_takes_them(engine: AsyncEngine) -> None:
    """system_extract, as Extract starts it: a read with no answer waits at its check with nothing on the file, an
    empty approve is refused, and an approve with the console's records list saves the typed values on the extraction
    as the person who decided, then the checked read on the file."""
    seeded = next(w for w in json.loads(EVENT_SEED.read_text()) if w["id"] == "system_extract")
    docs = NotRead()
    tenant, run_id, rt, w = await paused(
        engine, parse({**seeded, "id": f"sx_{uuid4().hex[:6]}"}), ports={"documents": docs, "file_data": docs}
    )
    assert docs.saved == [], "a read with no answer puts nothing on the file while it waits"
    typed: Json = {"invoice": "NWF-88213", "total": "1,940.00", "po": None}
    with tenant_scope(tenant):
        with pytest.raises(ValidationFailed) as empty:
            await engine_reviews.decide(rt, M, run_id, decision="approve", reason=None)
        await engine_reviews.decide(
            rt, M, run_id, decision="approve", reason=None, inputs={"edited": [{"values": typed}]}
        )
    assert empty.value.code == "required_fields_empty", empty.value
    await drain(w)
    assert await _outcome(engine, tenant, run_id) == "saved"
    sent = [{"field": "invoice", "value": "NWF-88213"}, {"field": "total", "value": "1,940.00"}]
    assert docs.corrected == [("ext_88213", sent, M.email)], docs.corrected
    assert [d["fieldsToCheck"] for d in docs.saved] == [0], docs.saved


class Answered(NotRead):
    """A read the model answered with one field under the floor: it waits at the same check, and the update changes
    nothing for it."""

    async def extract(self, run_id: str, file_id: str, request: Json, *, key: str) -> Any:
        doubtful = {"value": "PO-7", "extractedValue": "PO-7", "confidence": 0.41, "needsReview": True}
        sure = {"value": "NWF-41", "extractedValue": "NWF-41", "confidence": 0.97, "needsReview": False}
        return {
            "id": "ext_41",
            "status": "done",
            "outcome": "review",
            "fileId": "fil_41",
            "schema": SCHEMA,
            "fields": {"invoice": sure, "total": {**sure, "value": 410}, "po": doubtful},
            "needsReview": ["po"],
            "documentType": {"id": "freight_invoice", "version": 1, "name": "Freight invoice"},
        }


def _before_typed_values(seeded: Any) -> Any:
    """system_extract as it shipped before its check took typed values: no editable, approve straight to the save."""
    nodes: list[Any] = [dict(n) for n in seeded["nodes"] if n["id"] != "save_typed"]
    for n in nodes:
        if n["id"] == "check":
            n["parameters"] = {k: v for k, v in n["parameters"].items() if k != "editable"}
    ends = [(e, str(e["from"]["node"]), str(e["to"]["node"])) for e in seeded["connections"]]
    edges: list[Any] = [e for e, a, b in ends if "save_typed" not in (a, b)]
    edges.append({"from": {"node": "check", "port": "approve"}, "to": {"node": "save_checked", "port": "in"}})
    return {**seeded, "nodes": nodes, "connections": edges}


async def test_the_pending_extract_update_counts_the_tasks_that_can_only_be_rejected_until_it_is_live(
    engine: AsyncEngine,
) -> None:
    """A tenant still on the Extract from before typed values: its not-read tasks can only be rejected, and the update
    waiting in Reviews says how many it unlocks. A task on an answered read waits at the same step and is not one."""
    seeded = next(w for w in json.loads(EVENT_SEED.read_text()) if w["id"] == "system_extract")
    old = parse(_before_typed_values(seeded))
    tenant, tx = f"t-{uuid4().hex[:8]}", EngineTransactions(engine)
    w = worker(engine, CountingTools(), InMemorySaver())
    w.host.ports.task_types = StoredTaskTypes(engine)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            old.id, name="Extract a file", definition=old.wire(), digest=old.digest(), now="n", by=SEED, stage="live"
        )
    runs: list[str] = []
    for docs in (NotRead(), NotRead(), Answered()):
        for port in ("documents", "file_data"):
            setattr(w.host.ports, port, docs)
        run_id = new_id("wfrun")
        row = {"id": run_id, "team_id": "team_a", "workflow_id": old.id, "version": version, "digest": old.digest()}
        with tenant_scope(tenant):
            given = {"run_key": run_id, "mode": "live", "input": {"fileId": "fil_1"}, "created_by": "a@x"}
            await write_run(tx, row | given)
        await drain(w)
        runs.append(run_id)
    rt: Any = SimpleNamespace(
        db=engine,
        event_workflows=[seeded],
        event_workflows_seen=set(),
        policies=Policies({}),
        settings=SimpleNamespace(registry_auto_approve=False, environment="test", lease_ttl_seconds=6.0),
    )
    with tenant_scope(tenant):
        with pytest.raises(ValidationFailed) as refused:
            await engine_reviews.decide(rt, M, runs[0], decision="approve", reason=None)
        await ensure_event_workflows(rt)
        (req,) = await AgentRegistry(engine).requests(engine_lifecycle.KIND, old.id)
        review: Any = await engine_lifecycle.view(rt, req)
    assert refused.value.code == "not_editable", refused.value
    assert req.status == "pending", req
    assert review["publish"]["waitingTasks"] == 2, review["publish"]
