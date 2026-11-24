"""A read no model reply answered goes to a person to type, and the server holds approve until every required field
has a value, as the console holds the button, on PostgreSQL with the real worker, by failure mode: a call that skips
the console approves empty values; a typed value lost or an optional field blocking; a several-records read with no
records approved as zero records. The step names no task type, so the rule holds whatever type a workflow picks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api import engine_reviews
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RunStore
from ops_service_kit import narrow
from ops_service_kit.errors import ValidationFailed
from ops_service_kit.http import Json
from tests.engine.review_flows import flow, paused
from tests.engine.test_worker import M, drain

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
