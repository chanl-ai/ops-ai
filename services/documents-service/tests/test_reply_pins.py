"""The replies of the document type, extraction and reading routes, key by key and value by value, by failure mode: a
store row that changes its shape (a column renamed, a JSON column left as text, a datetime written another way)
changing what a caller is sent. Generated ids and times are replaced by their kind, so the rest is compared whole."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from .conftest import OPS, Make
from .test_document_types import FIELDS, TYPE, Models, Prices
from .test_extractions import NOTICE, Floor

PINS = Path(__file__).parent / "fixtures" / "reply-pins.json"
_TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(\+00:00|Z)?$")
_ID = re.compile(r"^([a-z]+)_[0-9a-f]{8,32}$")


def scrubbed(value: Any) -> Any:
    """`value` with every time, duration and generated id replaced by its kind, so two runs answer the same."""
    if isinstance(value, dict):
        # How long a read took is measured, so only its being a number is compared.
        return {k: "<ms>" if k == "durationMs" and isinstance(v, int) else scrubbed(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrubbed(v) for v in value]
    if isinstance(value, str) and (m := _TIME.match(value)):
        return f"<time{m.group(2) or ''}>"
    if isinstance(value, str) and (m := _ID.match(value)):
        return f"<{m.group(1)}>"
    return value


def data(r: httpx.Response, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return scrubbed(r.json()["data"])


async def test_the_document_type_extraction_and_reading_replies_keep_every_key_and_value(make: Make) -> None:
    s = make(Models(), Floor(0.5), Prices())
    seen: dict[str, Any] = {}
    async with s.client as c:
        base = "/v1/document-types/invoice_notice"
        seen["create"] = data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        more = {"fields": [*FIELDS, {"key": "customer", "type": "text"}], "note": "adds the customer"}
        seen["addVersion"] = data(await c.post(f"{base}/versions", json=more, headers=OPS), 201)
        fid = await s.stored(NOTICE)
        sample = {"fileId": fid, "expected": {"invoice": "INV-2207", "amount": "1,250.00"}}
        seen["addSample"] = data(await c.post(f"{base}/samples", json=sample, headers=OPS), 201)
        seen["list"] = data(await c.get("/v1/document-types", headers=OPS))
        seen["get"] = data(await c.get(base, headers=OPS))
        seen["getVersion"] = data(await c.get(f"{base}/versions/1", headers=OPS))
        seen["estimate"] = data(await c.get(f"{base}/versions/2/test-estimate", headers=OPS))
        started = await c.post(f"{base}/versions/2/test-runs", headers=OPS)
        seen["startTest"] = data(started, 202)
        await s.types.drain()
        test = await c.get(f"{base}/test-runs/{started.json()['data']['id']}", headers=OPS)
        seen["getTest"] = data(test)
        read = {"fileId": fid, "documentTypeId": "invoice_notice"}
        asked = await c.post("/v1/documents/extractions", json=read, headers=OPS)
        eid = asked.json()["data"]["id"]
        fix = {"value": "2207"}
        seen["correct"] = data(await c.patch(f"/v1/documents/extractions/{eid}/fields/invoice", json=fix, headers=OPS))
        seen["getExtraction"] = data(await c.get(f"/v1/documents/extractions/{eid}", headers=OPS))
        listed = await c.get("/v1/documents/extractions", params={"fileId": fid}, headers=OPS)
        seen["fileExtractions"] = data(listed)
        seen["examples"] = data(await c.get(f"{base}/examples", headers=OPS))
        seen["askReading"] = data(await c.post("/v1/documents/readings", json={"fileId": fid}, headers=OPS))
        seen["reading"] = data(await c.get(f"/v1/documents/readings/{fid}", headers=OPS))
    assert seen == json.loads(PINS.read_text()), json.dumps(seen, indent=2, sort_keys=True)
