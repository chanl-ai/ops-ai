"""The reply shapes the first pins leave out, key by key and value by value, by failure mode: a store row that changes
shape only where it is rare (a failure's error object, a record's correction, a list of expected records, a template
offer or suggestion, a reading still queued) changing what a caller is sent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from ops_documents import readings as readings_module
from ops_documents.extraction import ModelsService

from .conftest import OPS, Make
from .test_document_types import FIELDS, READ, Prices
from .test_extractions import NOTICE, Floor
from .test_reply_pins import data
from .test_template_suggestions import INVOICES, Reader, read_invoice
from .test_templates import INVOICE_TYPE

SHAPES = Path(__file__).parent / "fixtures" / "reply-shapes.json"
MANY = {"id": "notice_lines", "name": "Notice lines", "fields": FIELDS, "many": True}


class Records:
    """The model, answering a read of several records with two of them, and a read of one with its fields."""

    async def structured(self, system: str, user: str, schema: dict[str, Any], **kw: Any) -> Any:
        one = {k: v for k, v in READ.items() if k in ("invoice", "amount")}
        return {"records": [one, one]} if "records" in schema["properties"] else one


def _down() -> ModelsService:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"code": "internal", "message": "down"}})

    return ModelsService(httpx.AsyncClient(base_url="http://models", transport=httpx.MockTransport(answer)), "key")


async def test_failures_records_and_a_queued_reading_reply_as_before(
    make: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = make(Records(), Floor(0.5), Prices())
    seen: dict[str, Any] = {}
    base = "/v1/document-types/notice_lines"
    async with s.client as c:
        data(await c.post("/v1/document-types", json=MANY, headers=OPS), 201)
        gone = await s.stored(NOTICE, name="gone.txt")
        listed = {"fileId": gone, "expected": [{"invoice": "INV-2207"}, {"amount": "1,250.00 CAD"}]}
        seen["sampleList"] = data(await c.post(f"{base}/samples", json=listed, headers=OPS), 201)
        fid = await s.stored(NOTICE)
        typed = {"fileId": fid, "documentTypeId": "notice_lines"}
        read = (await c.post("/v1/documents/extractions", json=typed, headers=OPS)).json()["data"]
        fix = {"value": "2208", "record": 1}
        path = f"/v1/documents/extractions/{read['id']}/fields/invoice"
        seen["correctRecord"] = data(await c.patch(path, json=fix, headers=OPS))
        s.files.files.pop(gone)
        started = await c.post(f"{base}/versions/1/test-runs", headers=OPS)
        await s.types.drain()
        test = await c.get(f"{base}/test-runs/{started.json()['data']['id']}", headers=OPS)
        seen["failedTest"] = data(test)
        broken = await s.stored(b"%PDF-1.4 not a pdf", name="broken.pdf", mime="application/pdf")
        seen["failedReading"] = data(await c.post("/v1/documents/readings", json={"fileId": broken}, headers=OPS))
        monkeypatch.setattr(readings_module, "SYNC_BYTES", 1)
        later = await s.stored(NOTICE + b"\n")
        seen["queuedReading"] = data(await c.post("/v1/documents/readings", json={"fileId": later}, headers=OPS), 202)
        assert s.extractor.readings is not None
        await s.extractor.readings.drain()
    down = make(_down(), Floor(0.5), Prices())
    async with down.client as c:
        fid = await down.stored(NOTICE)
        body = {"fileId": fid, "fields": FIELDS}
        seen["failedExtraction"] = data(await c.post("/v1/documents/extractions", json=body, headers=OPS))
    assert seen == {k: json.loads(SHAPES.read_text())[k] for k in seen}, json.dumps(seen, indent=2, sort_keys=True)


async def test_a_template_offer_and_a_suggestion_reply_as_before(make: Make) -> None:
    model = Reader()
    s = make(model, Floor())
    url = "/v1/document-types/supplier_invoice"
    seen: dict[str, Any] = {}
    async with s.client as c:
        data(await c.post("/v1/document-types", json=INVOICE_TYPE, headers=OPS), 201)
        ids = [await read_invoice(s, c, model, v) for v in INVOICES[:5]]
        seen["offers"] = data(await c.get(f"{url}/template-offers", headers=OPS))
        suggest = {"extractionIds": ids[:2]}
        seen["suggest"] = data(await c.post(f"{url}/templates/suggest", json=suggest, headers=OPS))
    assert seen == {k: json.loads(SHAPES.read_text())[k] for k in seen}, json.dumps(seen, indent=2, sort_keys=True)
