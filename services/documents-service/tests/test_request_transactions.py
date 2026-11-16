"""When a documents request holds the database, by failure mode: files-service or the model asked while the request's
transaction is open, so every slow file read or model answer holds a pooled connection; and a route that reads or
writes only rows spread over a transaction per statement, so a failure part-way keeps half its writes."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store import engine_for
from ops_documents.store.extractions import extractions
from ops_documents.store.readings import documents_reading_files, documents_reading_pages, documents_readings
from ops_service_kit.logging import captured_logging
from ops_service_kit.request_timing import current

from .conftest import OPS, Make
from .test_classify import Models as Classifier
from .test_document_types import FIELDS, TYPE, Prices, data
from .test_extractions import NOTICE, Floor
from .test_template_suggestions import INVOICES, Reader, read_invoice
from .test_templates import INVOICE_TYPE


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """The service's own engine, whose statements and transactions the request line counts."""
    made = engine_for(database_url)
    yield made
    await made.dispose()


class HeldModels(Classifier):
    """The model, noting how many transactions the request holds open while it answers."""

    def __init__(self) -> None:
        super().__init__("invoice_notice", 0.95)
        self.open: list[int] = []

    async def structured(self, system: str, user: str, schema: dict[str, Any], **kw: Any) -> Any:
        timing = current()
        assert timing is not None, "the model is asked inside the request"
        self.open.append(timing.db_tx_open)
        return await super().structured(system, user, schema, **kw)


def lines(text: str) -> list[dict[str, Any]]:
    return [x for x in (json.loads(t) for t in text.splitlines()) if x.get("event") == "http.request"]


async def test_no_file_read_or_model_call_is_made_while_a_transaction_is_open(make: Make) -> None:
    models = HeldModels()
    s = make(models, Floor(0.5), Prices())
    with captured_logging("documents-transactions") as stream:
        async with s.client as c:
            data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
            fid = await s.stored(NOTICE)
            read = {"fileId": fid, "documentTypeId": "invoice_notice"}
            eid = data(await c.post("/v1/documents/extractions", json=read, headers=OPS))["id"]
            data(await c.post("/v1/documents/classifications", json={"fileId": fid}, headers=OPS))
            data(await c.post("/v1/documents/layout", json={"fileId": fid}, headers=OPS))
            data(await c.post("/v1/documents/readings", json={"fileId": fid}, headers=OPS))
            data(await c.get(f"/v1/documents/readings/{fid}", headers=OPS))
            data(await c.get(f"/v1/documents/layout/{fid}", headers=OPS))
            data(await c.get("/v1/documents/extractions", params={"fileId": fid}, headers=OPS))
            data(await c.get(f"/v1/documents/extractions/{eid}", headers=OPS))
    held = [(x["http.route"], x["http.client.calls_in_tx"]) for x in lines(stream.getvalue())]
    assert models.open and set(models.open) == {0}, models.open
    assert all(n == 0 for _, n in held), held


async def test_a_route_that_reads_or_writes_only_rows_is_one_transaction(make: Make) -> None:
    s = make(HeldModels(), Floor(0.5), Prices())
    base = "/v1/document-types/invoice_notice"
    with captured_logging("documents-transactions") as stream:
        async with s.client as c:
            data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
            fid = await s.stored(NOTICE)
            read = {"fileId": fid, "documentTypeId": "invoice_notice"}
            eid = data(await c.post("/v1/documents/extractions", json=read, headers=OPS))["id"]
            stream.truncate(0)
            stream.seek(0)
            data(await c.get("/v1/document-types", headers=OPS))
            data(await c.get(base, headers=OPS))
            data(await c.post(f"{base}/versions", json={"fields": FIELDS, "note": "again"}, headers=OPS), 201)
            data(await c.get(f"{base}/versions/2", headers=OPS))
            data(await c.patch(f"/v1/documents/extractions/{eid}/fields/invoice", json={"value": "2207"}, headers=OPS))
            data(await c.get(f"/v1/documents/extractions/{eid}", headers=OPS))
    seen = {(x["http.request.method"], x["http.route"]): x["db.tx_count"] for x in lines(stream.getvalue())}
    assert len(seen) == 6 and set(seen.values()) == {1}, seen


class HeldUses:
    """agents-service's answer of which workflows read a type, noting the transactions open while it answers."""

    def __init__(self, held: list[int]) -> None:
        self.held = held

    async def of(self, who: Any, type_id: str) -> list[dict[str, str]]:
        _note(self.held)
        return []


class HeldPrices(Prices):
    def __init__(self, held: list[int]) -> None:
        self.held = held

    async def price(self, alias: str, *, tenant: str) -> Any:
        _note(self.held)
        return await super().price(alias, tenant=tenant)


def _note(held: list[int]) -> None:
    timing = current()
    assert timing is not None, "the other service is asked inside the request"
    held.append(timing.db_tx_open)


def _held_files(s: Any, held: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
    files = s.extractor.files
    for name in ("readable", "read", "keep", "release"):
        real = getattr(files, name)

        async def noted(*a: Any, _real: Any = real, **kw: Any) -> Any:
            _note(held)
            return await _real(*a, **kw)

        monkeypatch.setattr(files, name, noted)


async def test_a_type_route_that_asks_another_service_gates_then_settles_with_none_open_at_the_call(
    make: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    held: list[int] = []
    s = make(HeldModels(), Floor(0.5), HeldPrices(held), type_uses=HeldUses(held))
    _held_files(s, held, monkeypatch)
    base = "/v1/document-types/invoice_notice"
    with captured_logging("documents-transactions") as stream:
        async with s.client as c:
            data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
            fid = await s.stored(NOTICE)
            sample = data(await c.post(f"{base}/samples", json={"fileId": fid, "expected": {}}, headers=OPS), 201)
            data(await c.get(f"{base}/examples", headers=OPS))
            data(await c.get(f"{base}/template-offers", headers=OPS))
            data(await c.get(f"{base}/versions/1/test-estimate", headers=OPS))
            data(await c.post(f"{base}/versions/1/test-runs", headers=OPS), 202)
            await s.types.drain()
            assert (await c.delete(f"{base}/samples/{sample['id']}", headers=OPS)).status_code == 204
            assert (await c.delete(base, headers=OPS)).status_code == 204
    seen = {(x["http.request.method"], x["http.route"]): x["db.tx_count"] for x in lines(stream.getvalue())}
    t = "/v1/document-types/{type_id}"
    assert seen == {
        ("POST", "/v1/document-types"): 1,
        # The type's latest version checked, files-service asked to keep the file, then the sample saved.
        ("POST", f"{t}/samples"): 2,
        ("GET", f"{t}/examples"): 1,
        ("GET", f"{t}/template-offers"): 1,
        ("GET", f"{t}/versions/{{version}}/test-estimate"): 1,
        # The run's row commits before the task that runs it starts.
        ("POST", f"{t}/versions/{{version}}/test-runs"): 1,
        ("DELETE", f"{t}/samples/{{sample_id}}"): 1,
        # The type read, agents-service asked which workflows read it, then the delete.
        ("DELETE", t): 2,
    }, seen
    assert held and set(held) == {0}, held


class Down:
    """agents-service out of reach while a type is deleted."""

    async def of(self, who: Any, type_id: str) -> list[dict[str, str]]:
        raise RuntimeError("agents-service is out of reach")


async def test_when_the_outside_call_fails_the_gate_leaves_nothing_half_written(
    make: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = make(HeldModels(), Floor(0.5), Prices(), type_uses=Down())

    async def refused(*a: Any, **kw: Any) -> None:
        raise RuntimeError("files-service is out of reach")

    monkeypatch.setattr(s.extractor.files, "keep", refused)
    base = "/v1/document-types/invoice_notice"
    async with s.client as c:
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        fid = await s.stored(NOTICE)
        added = await c.post(f"{base}/samples", json={"fileId": fid, "expected": {}}, headers=OPS)
        deleted = await c.delete(base, headers=OPS)
        estimate = data(await c.get(f"{base}/versions/1/test-estimate", headers=OPS))
        kept = data(await c.get(base, headers=OPS))
    assert (added.status_code, deleted.status_code) == (500, 500), (added.text, deleted.text)
    assert estimate["samples"] == 0, "a sample whose file files-service did not keep is not saved"
    assert kept["id"] == "invoice_notice", "a type whose readers could not be asked is not deleted"


async def test_a_reading_or_layout_read_now_is_a_gate_and_a_settle_and_a_stored_one_a_single_read(make: Make) -> None:
    s = make(HeldModels(), Floor(0.5), Prices())
    with captured_logging("documents-transactions") as stream:
        async with s.client as c:
            fid = await s.stored(NOTICE)
            other = await s.stored(NOTICE + b"\n")
            for _ in range(2):
                data(await c.post("/v1/documents/readings", json={"fileId": fid}, headers=OPS))
                data(await c.post("/v1/documents/layout", json={"fileId": other}, headers=OPS))
    seen = [(x["http.route"], x["db.tx_count"]) for x in lines(stream.getvalue())]
    reading, layout = "/v1/documents/readings", "/v1/documents/layout"
    # Read now: the stored reading looked up, the bytes read with none open, then the reading kept. Asked again: one.
    assert seen == [(reading, 2), (layout, 2), (reading, 1), (layout, 1)], seen


async def test_a_template_suggestion_reads_its_rows_in_one_gate_and_each_layout_with_none_open_at_a_call(
    make: Make, monkeypatch: pytest.MonkeyPatch, engine: AsyncEngine
) -> None:
    model = Reader()
    s = make(model, Floor(0.5))
    held: list[int] = []
    _held_files(s, held, monkeypatch)
    url = "/v1/document-types/supplier_invoice/templates/suggest"
    async with s.client as c:
        data(await c.post("/v1/document-types", json=INVOICE_TYPE, headers=OPS), 201)
        first = await read_invoice(s, c, model, INVOICES[0])
        second = await read_invoice(s, c, model, INVOICES[1])
        # The first read's reading is no longer stored, so its layout is read again from files-service.
        async with engine.begin() as conn:
            r, p, f = documents_readings, documents_reading_pages, documents_reading_files
            fid = (await conn.execute(sa.select(extractions.c.file_id).where(extractions.c.id == first))).scalar_one()
            digest = sa.select(f.c.file_digest).where(f.c.tenant_id == s.tenant, f.c.file_id == fid)
            for t in (p, r):
                await conn.execute(sa.delete(t).where(t.c.tenant_id == s.tenant, t.c.file_digest.in_(digest)))
        held.clear()
        with captured_logging("documents-transactions") as stream:
            data(await c.post(url, json={"extractionIds": [first, second]}, headers=OPS))
    [line] = lines(stream.getvalue())
    # The type, both rows and the latest version in one; the first layout looked up, read with none open and kept
    # (three); the second found stored (one).
    assert line["db.tx_count"] == 5, line
    assert held and set(held) == {0}, held
