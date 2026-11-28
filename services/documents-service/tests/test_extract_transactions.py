"""When an extraction holds the database, by failure mode: files-service, platform-service or the model asked while a
transaction is open, so a slow answer holds a pooled connection; a settle spread over a transaction per statement; and
the row a failure leaves behind (the model refusing or timing out, files-service out of reach, the caller gone) changed
by where a transaction opens or closes. Each failure is pinned on the request path and on the queued path."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents import extraction
from ops_documents.extraction import ModelsService
from ops_documents.store import engine_for
from ops_service_kit.logging import captured_logging
from ops_service_kit.request_timing import current

from .conftest import OPS, Make, Service
from .test_document_types import TYPE, Prices, data
from .test_document_types import Models as Reader
from .test_extractions import NOTICE, Floor

READ = {"fileId": "", "documentTypeId": "invoice_notice"}


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """The service's own engine, whose statements and transactions the request line counts."""
    made = engine_for(database_url)
    yield made
    await made.dispose()


def _note(held: list[int]) -> None:
    timing = current()
    if timing is not None:
        held.append(timing.db_tx_open)


class HeldReader(Reader):
    def __init__(self, held: list[int]) -> None:
        super().__init__()
        self.held = held

    async def structured(self, system: str, user: str, schema: dict[str, Any], **kw: Any) -> Any:
        _note(self.held)
        return await super().structured(system, user, schema, **kw)


class HeldFloor(Floor):
    def __init__(self, held: list[int]) -> None:
        super().__init__(0.5)
        self.held = held

    async def floor(self, tenant: str, team: str) -> float:
        _note(self.held)
        return await super().floor(tenant, team)


def _held_files(s: Service, held: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
    files = s.extractor.files
    for name in ("readable", "read"):
        real = getattr(files, name)

        async def noted(*a: Any, _real: Any = real, **kw: Any) -> Any:
            _note(held)
            return await _real(*a, **kw)

        monkeypatch.setattr(files, name, noted)


def _requests(text: str) -> list[dict[str, Any]]:
    return [x for x in (json.loads(t) for t in text.splitlines()) if x.get("event") == "http.request"]


async def test_an_extraction_gates_reads_and_settles_once_with_none_open_at_a_call(
    make: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    held: list[int] = []
    s = make(HeldReader(held), HeldFloor(held), Prices())
    _held_files(s, held, monkeypatch)
    async with s.client as c:
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        fid = await s.stored(NOTICE)
        with captured_logging("documents-extract") as stream:
            done = data(await c.post("/v1/documents/extractions", json=READ | {"fileId": fid}, headers=OPS))
    assert done["status"] == "done", done
    [line] = _requests(stream.getvalue())
    # The type and its version; the row saved; the reading's gate and settle; the row started; the type's examples,
    # read between the floor and the model; then the answer saved and read back.
    assert line["db.tx_count"] == 7, line
    assert held and set(held) == {0}, held


class Parked:
    """The model, answering only once the test lets it, so the caller can leave while it thinks."""

    def __init__(self) -> None:
        self.asked = asyncio.Event()

    async def structured(self, *a: Any, **kw: Any) -> Any:
        self.asked.set()
        await asyncio.Event().wait()


def _models(fail: str) -> ModelsService:
    def answer(request: httpx.Request) -> httpx.Response:
        if fail == "timeout":
            raise httpx.ReadTimeout("models-service took too long", request=request)
        return httpx.Response(500, json={"error": {"code": "internal", "message": "down"}})

    return ModelsService(httpx.AsyncClient(base_url="http://models", transport=httpx.MockTransport(answer)), "key")


async def _unreachable(*a: Any, **kw: Any) -> bytes:
    raise httpx.ConnectError("files-service is out of reach")


async def _rows(c: httpx.AsyncClient, fid: str) -> list[dict[str, Any]]:
    return data(await c.get("/v1/documents/extractions", params={"fileId": fid}, headers=OPS))["data"]


@pytest.mark.parametrize("queued", [False, True], ids=["request", "queued"])
@pytest.mark.parametrize("fail", ["model_error", "model_timeout", "files_unreachable"])
async def test_a_failed_extraction_leaves_the_row_it_left_before(
    make: Make, monkeypatch: pytest.MonkeyPatch, fail: str, queued: bool
) -> None:
    if queued:
        monkeypatch.setattr(extraction, "SYNC_BYTES", 10)  # every file is large: queued, run as a task
    s = make(_models(fail.removeprefix("model_")) if fail.startswith("model") else Reader(), Floor(0.5), Prices())
    async with s.client as c:
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        fid = await s.stored(NOTICE)
        if fail == "files_unreachable":
            monkeypatch.setattr(s.extractor.files, "read", _unreachable)
        r = await c.post("/v1/documents/extractions", json=READ | {"fileId": fid}, headers=OPS)
        await s.extractor.drain()
        [row] = await _rows(c, fid)
    error: dict[str, Any] = row.get("error") or {}
    left = (r.status_code, row["status"], error.get("code"))
    expected = {
        (False, "model_error"): (200, "failed", "model_unavailable"),
        (False, "model_timeout"): (200, "failed", "model_late"),
        # The reading's bytes could not be read after the row was saved: it is settled failed, so a retry runs again.
        (False, "files_unreachable"): (500, "failed", "failed"),
        (True, "model_error"): (202, "failed", "model_unavailable"),
        (True, "model_timeout"): (202, "failed", "model_late"),
        (True, "files_unreachable"): (202, "failed", "failed"),
    }[(queued, fail)]
    assert left == expected, (left, r.text, row)


async def test_a_caller_who_leaves_while_the_model_reads_settles_the_row_failed(make: Make) -> None:
    """The read was this request's own, so a cancel settles it failed and a same-key retry runs again now."""
    model = Parked()
    s = make(model, Floor(0.5), Prices())
    async with s.client as c:
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        fid = await s.stored(NOTICE)
        asked = asyncio.ensure_future(c.post("/v1/documents/extractions", json=READ | {"fileId": fid}, headers=OPS))
        await model.asked.wait()
        asked.cancel()
        with suppress(asyncio.CancelledError):
            await asked
        [row] = await _rows(c, fid)
    assert row["status"] == "failed" and row["error"]["code"] == "failed", row
