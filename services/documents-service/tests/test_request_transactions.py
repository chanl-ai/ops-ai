"""When a documents request holds the database, by failure mode: files-service or the model asked while the request's
transaction is open, so every slow file read or model answer holds a pooled connection; and a route that reads or
writes only rows spread over a transaction per statement, so a failure part-way keeps half its writes."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store import engine_for
from ops_service_kit.logging import captured_logging
from ops_service_kit.request_timing import current

from .conftest import OPS, Make
from .test_classify import Models as Classifier
from .test_document_types import FIELDS, TYPE, Prices, data
from .test_extractions import NOTICE, Floor


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
