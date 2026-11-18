"""The replies of the document type, extraction and reading routes, key by key and value by value, by failure mode: a
store row that changes its shape (a column renamed, a JSON column left as text, a datetime written another way)
changing what a caller is sent. Generated ids and times are replaced by their kind, so the rest is compared whole."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store.document_types import document_type_versions, document_types
from ops_identity import dev_service_signer, mint_service_token

from .conftest import OPS, Make
from .test_classify import Models as Classifier
from .test_document_types import FIELDS, TYPE, Models, Prices
from .test_extractions import NOTICE, Floor
from .test_templates_install import LETTER, SOURCE, install, listed, wire

PINS = Path(__file__).parent / "fixtures" / "reply-pins.json"
_TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(\+00:00|Z)?$")
_ID = re.compile(r"^([a-z]+)_[0-9a-f]{8,32}$")


def scrubbed(value: Any) -> Any:
    """`value` with every time, duration and generated id replaced by its kind, so two runs answer the same."""
    if isinstance(value, dict):
        # How long a read took is measured, so only its being a number is compared.
        held = cast(dict[str, object], value)
        return {k: "<ms>" if k == "durationMs" and isinstance(v, int) else scrubbed(v) for k, v in held.items()}
    if isinstance(value, list):
        return [scrubbed(v) for v in cast(list[object], value)]
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


async def test_a_version_saved_before_its_options_existed_reads_as_their_defaults(
    make: Make, engine: AsyncEngine
) -> None:
    """A version row from before templates, checks, the date order, page images and offerAt were columns holds null in
    each; it answers as the defaults, never as null and never as an error."""
    s = make(Models(), Floor(0.5), Prices())
    async with s.client as c:
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        async with engine.begin() as conn:
            v = document_type_versions.c
            old = {"templates": None, "checks": None, "date_order": None, "page_images": None, "offer_at": None}
            await conn.execute(
                sa.update(document_type_versions)
                .where(v.tenant_id == s.tenant, v.type_id == "invoice_notice")
                .values(**old)
            )
            t = document_types.c
            await conn.execute(sa.update(document_types).where(t.tenant_id == s.tenant).values(description="older"))
        got = data(await c.get("/v1/document-types/invoice_notice", headers=OPS))
        version = data(await c.get("/v1/document-types/invoice_notice/versions/1", headers=OPS))
    assert version == got["versions"][0], (version, got)
    assert {k: v for k, v in got.items() if k != "versions"} == {
        "id": "invoice_notice",
        "name": "Invoice notice",
        "description": "older",
        "team": "team_ops",
        "latestVersion": 1,
        "createdBy": "j.richardson@harborpine.example",
        "createdAt": "<time+00:00>",
        "samples": [],
        "canEdit": True,
    }, got
    assert version == {
        "version": 1,
        "fields": json.loads(PINS.read_text())["create"]["versions"][0]["fields"],
        "many": False,
        "reviewBelow": None,
        "dateOrder": "MDY",
        "templates": [],
        "checks": [],
        "pageImages": False,
        "offerAt": 5,
        "note": None,
        "createdBy": "j.richardson@harborpine.example",
        "createdAt": "<time+00:00>",
    }, version


ROUTE_PINS = Path(__file__).parent / "fixtures" / "reply-pins-routes.json"


async def test_the_layout_purge_classify_and_template_replies_keep_every_key_and_value(make: Make) -> None:
    """The routes the first pin leaves out: a read's own reply, classify, layout, purge, delete, and the template
    copy routes, with each status."""
    s = make(Classifier("invoice_notice", 0.95), Floor(0.5), Prices())
    wire(s, [LETTER])
    seen: dict[str, Any] = {}
    token = mint_service_token(
        dev_service_signer(),
        service="agents",
        audience="documents",
        tenant_id=s.tenant,
        scopes=["documents:delete"],
        team_id="team_ops",
    )
    async with s.client as c:
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        fid = await s.stored(NOTICE)
        read = {"fileId": fid, "documentTypeId": "invoice_notice"}
        seen["extract"] = data(await c.post("/v1/documents/extractions", json=read, headers=OPS))
        seen["classify"] = data(await c.post("/v1/documents/classifications", json={"fileId": fid}, headers=OPS))
        seen["layoutBefore"] = data(await c.get(f"/v1/documents/layout/{fid}", headers=OPS))
        seen["layout"] = data(await c.post("/v1/documents/layout", json={"fileId": fid}, headers=OPS))
        seen["layoutPage"] = data(await c.get(f"/v1/documents/layout/{fid}", params={"page": 1}, headers=OPS))
        seen["offers"] = data(await c.get("/v1/document-types/invoice_notice/template-offers", headers=OPS))
        seen["templates"] = await listed(s)
        copy = await install(s)
        seen["copy"] = data(copy, 201)
        made = copy.json()["data"]["copy"]["recordId"]
        seen["copyAgain"] = data(await install(s))
        path = f"/v1/resources/{SOURCE}:case-letter/copies/{made}"
        review = await c.get(f"{path}/update", headers=OPS)
        seen["review"] = data(review)
        seen["take"] = data(
            await c.post(f"{path}/update", json={"expect": review.json()["data"]["expect"]}, headers=OPS)
        )
        seen["detach"] = data(await c.post(f"{path}/detach", headers=OPS))
        gone = await c.delete(f"/v1/document-types/{made}", headers=OPS)
        seen["delete"] = [gone.status_code, gone.text]
        s.files.files.pop(fid)
        seen["purge"] = data(
            await c.post("/v1/documents/purge", json={"fileId": fid}, headers={"Authorization": f"Bearer {token}"})
        )
    assert seen == json.loads(ROUTE_PINS.read_text()), json.dumps(seen, indent=2, sort_keys=True)


_MISSING = "fil_missing0000000000000000000000"
_TYPES = "/v1/document-types/no_such_type"
# The bodies the routes accept: (path, method, body, the status a parsed body gets). A body model moved to another base
# that stops taking a field's camelCase or snake_case name, or takes a field it never named, fails here. A parsed body
# reaches the route, which answers the missing file or type.
_BODIES: list[tuple[str, str, dict[str, Any], int]] = [
    (
        "/v1/documents/extractions",
        "post",
        {"fileId": _MISSING, "fields": FIELDS, "reviewBelow": 0.5, "maxPages": 1},
        404,
    ),
    (
        "/v1/documents/extractions",
        "post",
        {"file_id": _MISSING, "fields": FIELDS, "review_below": 0.5, "max_pages": 1},
        404,
    ),
    ("/v1/documents/classifications", "post", {"fileId": _MISSING}, 404),
    ("/v1/documents/classifications", "post", {"file_id": _MISSING}, 404),
    ("/v1/documents/readings", "post", {"fileId": _MISSING, "language": "eng"}, 404),
    ("/v1/documents/readings", "post", {"file_id": _MISSING, "language": "eng"}, 404),
    ("/v1/documents/layout", "post", {"fileId": _MISSING}, 404),
    ("/v1/documents/layout", "post", {"file_id": _MISSING}, 404),
    ("/v1/documents/extractions/ext_missing/fields/invoice", "patch", {"value": "1"}, 404),
    (
        "/v1/document-types",
        "post",
        {**TYPE, "id": "pinned_a", "name": "A", "reviewBelow": 0.5, "dateOrder": "DMY"},
        201,
    ),
    (
        "/v1/document-types",
        "post",
        {**TYPE, "id": "pinned_b", "name": "B", "review_below": 0.5, "date_order": "DMY"},
        201,
    ),
    (f"{_TYPES}/versions", "post", {"fields": FIELDS, "offerAt": 5, "pageImages": False}, 404),
    (f"{_TYPES}/versions", "post", {"fields": FIELDS, "offer_at": 5, "page_images": False}, 404),
    (f"{_TYPES}/templates/suggest", "post", {"extractionIds": ["ext_1"]}, 404),
    (f"{_TYPES}/templates/suggest", "post", {"extraction_ids": ["ext_1"]}, 404),
    (f"{_TYPES}/samples", "post", {"fileId": _MISSING, "expected": {}}, 404),
    (f"{_TYPES}/samples", "post", {"file_id": _MISSING, "expected": {}}, 404),
]


async def test_each_body_takes_both_names_of_a_field_and_refuses_an_unknown_one(make: Make) -> None:
    s = make(Models(), Floor(0.5), Prices())
    got: list[tuple[str, int, int]] = []
    async with s.client as c:
        for path, method, body, _ in _BODIES:
            known = await c.request(method, path, json=body, headers=OPS)
            unknown = await c.request(method, path, json={**body, "teamName": "ops"}, headers=OPS)
            got.append((path, known.status_code, unknown.status_code))
    assert got == [(path, parsed, 400) for path, _, _, parsed in _BODIES], got
