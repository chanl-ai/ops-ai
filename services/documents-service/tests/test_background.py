"""The service's background processes as agents-service's Background page reads them: GET /health/background lists
each with its state, and a pass that fails shows there."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_documents import extraction
from ops_documents.store import documents_relay
from ops_documents.store.readings import ReadingRow
from ops_store.outbox import run_relay
from ops_store.testing import loop_reports_failure

from .conftest import OPS, Make
from .test_document_types import TYPE, Models, Prices
from .test_extractions import NOTICE, Floor, extract
from .test_extractions import Models as Reading
from .test_readings import ask, pages_pdf

FAILED = "background_task_failed"


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
    make: Make, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The run cannot write its status (the database refuses), so neither its result nor its failure is kept: the
    document reading process shows the failure instead of reading as running, and the next run still finishes."""
    caplog.set_level(logging.WARNING, logger="ops_store.background")
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
        monkeypatch.undo()
        good = (await c.post("/v1/document-types/invoice_notice/versions/1/test-runs", headers=OPS)).json()["data"]
        await s.types.drain()
        done = (await c.get(f"/v1/document-types/invoice_notice/test-runs/{good['id']}", headers=OPS)).json()["data"]
    assert done["status"] == "done", done
    assert FAILED in caplog.text and "the database refused the write" in caplog.text, caplog.text


@pytest.mark.lifespan_supervisor
async def test_a_queued_reading_that_fails_starts_the_next_and_reports_on_health(
    make: Make, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One slot, on the app's own lifespan: the reading behind a failed one starts from the failed one's task, the
    failure is logged and shown on /health/background, and drain returns once the second is read."""
    caplog.set_level(logging.WARNING, logger="ops_store.background")
    s = make(Models(), Floor())
    readings = s.extractor.readings
    assert readings is not None
    readings.slots = 1
    real_start, gate, asked = readings.store.start, asyncio.Event(), list[asyncio.Task[None]]()
    failing = await s.stored(pages_pdf(8), name="failing.pdf", mime="application/pdf")
    good = await s.stored(pages_pdf(7), name="good.pdf", mime="application/pdf")

    async def start(row: ReadingRow, *, at: Any) -> int:
        if row.file_id == failing:
            raise OSError("the database refused the write")
        await gate.wait()
        return await real_start(row, at=at)

    monkeypatch.setattr(readings.store, "start", start)

    async def both(c: httpx.AsyncClient) -> None:
        assert (await ask(c, failing)).status_code == 202
        assert (await ask(c, good)).status_code == 202

    async with s.client as c, s.app.router.lifespan_context(s.app):
        await loop_reports_failure(c, "document_reading", lambda: asked.append(asyncio.create_task(both(c))))
        await asked[0]
        gate.set()
        await readings.drain()
        read = (await c.get(f"/v1/documents/readings/{good}", headers=OPS)).json()["data"]
    assert read["status"] == "done" and read["pagesDone"] == 7, read
    assert FAILED in caplog.text and "the database refused the write" in caplog.text, caplog.text


async def test_an_extraction_that_cannot_settle_reports_on_health_and_the_next_one_runs(
    make: Make, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The extraction cannot be marked running nor failed (the database refuses), so it escapes its task: the failure
    is logged and shown on /health/background, drain still returns, and the next extraction is read."""
    caplog.set_level(logging.WARNING, logger="ops_store.background")
    monkeypatch.setattr(extraction, "SYNC_BYTES", 10)  # every file is read in the background
    s = make(Reading(), Floor())
    asked: list[asyncio.Task[httpx.Response]] = []

    async def refused(*args: Any, **kwargs: Any) -> Any:
        raise OSError("the database refused the write")

    def trip() -> None:
        monkeypatch.setattr(s.extractor.store, "start", refused)
        monkeypatch.setattr(s.extractor.store, "finish", refused)
        asked.append(asyncio.get_running_loop().create_task(extract(c, failing)))

    async with s.client as c:
        failing = await s.stored(NOTICE)
        await loop_reports_failure(c, "document_reading", trip)
        assert (await asked[0]).status_code == 202
        await s.extractor.drain()
        monkeypatch.undo()
        monkeypatch.setattr(extraction, "SYNC_BYTES", 10)
        good = (await extract(c, await s.stored(NOTICE + b"Second copy\n"))).json()["data"]
        await s.extractor.drain()
        done = (await c.get(f"/v1/documents/extractions/{good['id']}", headers=OPS)).json()["data"]
    assert done["status"] == "done", done
    assert FAILED in caplog.text and "the database refused the write" in caplog.text, caplog.text
