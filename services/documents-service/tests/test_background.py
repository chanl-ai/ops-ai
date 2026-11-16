"""The service's background processes as agents-service's Background page reads them: GET /health/background lists
each with its state, and a pass that fails shows there."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_documents.store import documents_relay
from ops_store.outbox import run_relay
from ops_store.testing import loop_reports_failure

from .conftest import OPS, Make
from .test_document_types import TYPE, Models, Prices
from .test_extractions import NOTICE, Floor


async def test_health_background_lists_each_process_with_its_state(make: Make) -> None:
    s = make()
    async with s.client as c:
        answer = await c.get("/health/background")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert set(body) == {"processes"}, body
    rows = {p["key"]: p for p in body["processes"]}
    assert set(rows) == {"documents_relay", "document_reading"}, rows
    assert set(rows["documents_relay"]) == {
        "key", "service", "title", "does", "everySeconds", "state", "instances", "lastRunAt", "nextRunAt",
        "doneHour", "waiting", "lastError", "lastErrorAt",
    }, rows  # fmt: skip


async def test_the_relay_reports_a_failed_pass_on_health(make: Make, engine: AsyncEngine) -> None:
    class Agents:
        async def post(self, path: str, body: Any, /, *, tenant: str, team: str) -> None: ...

    outbox = documents_relay(engine, {"agents": Agents()})
    stop = asyncio.Event()
    s = make(background=[lambda: run_relay(outbox, key="documents_relay", stop=stop)])
    # The database goes away: the next pass cannot read the outbox at all.
    gone = create_async_engine("sqlite+aiosqlite://")
    try:
        async with s.client as c, s.app.router.lifespan_context(s.app):
            await loop_reports_failure(c, "documents_relay", lambda: setattr(outbox, "engine", gone))
    finally:
        stop.set()
        await gone.dispose()


async def test_a_document_type_test_that_cannot_record_its_end_reports_on_health(
    make: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run cannot write its status (the database refuses), so neither its result nor its failure is kept: the
    document reading process shows the failure instead of reading as running."""
    s = make(Models(), Floor(), Prices())
    started: list[asyncio.Task[httpx.Response]] = []

    async def refused(test_id: str, values: Any) -> None:
        raise OSError("the database refused the write")

    def trip() -> None:
        monkeypatch.setattr(s.types.store, "set_test", refused)
        test_run = c.post("/v1/document-types/invoice_notice/versions/1/test-runs", headers=OPS)
        started.append(asyncio.get_running_loop().create_task(test_run))

    async with s.client as c:
        assert (await c.post("/v1/document-types", json=TYPE, headers=OPS)).status_code == 201
        sample = {"fileId": await s.stored(NOTICE), "expected": {"invoice": "INV-2207"}}
        assert (await c.post("/v1/document-types/invoice_notice/samples", json=sample, headers=OPS)).status_code == 201
        await loop_reports_failure(c, "document_reading", trip)
        assert (await started[0]).status_code == 202
        await s.types.drain()
