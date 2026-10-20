"""Template suggestions and offers through the API (c-254), on invoices printed from one master: a suggestion from one
read, saved as a version, reads another invoice with no model call (F1, F2); suggesting saves nothing (F3); offers
appear at 5 checked reads of one layout, never for another layout or one a template already reads (F4); a read of
another type or one the team cannot see feeds no suggestion (F5)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store.extractions import extractions

from .conftest import OPS, Make
from .test_extractions import Floor
from .test_templates import FIELDS, INVOICE_LABELS, INVOICE_TYPE, STATEMENT_LABELS, data, form

INVOICES = [
    {"invoice_no": f"INV-3{n}021", "vendor": vendor, "total": total, "due": f"12/{10 + n}/2026"}
    for n, (vendor, total) in enumerate(
        [
            ("Harbour Supplies Ltd", "$1,250.00"),
            ("Northern Paper Co", "$318.40"),
            ("Bluewater Logistics", "$7,004.15"),
            ("Kestrel Office Goods", "$99.99"),
            ("Pinecrest Catering", "$2,410.00"),
            ("Ridgeway Print Shop", "$56.20"),
        ]
    )
]


class Reader:
    """The model, answering each read with the next invoice's values quoted as printed."""

    def __init__(self) -> None:
        self.queue: list[dict[str, str]] = []
        self.calls = 0

    async def structured(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        values = self.queue.pop(0)
        return {k: {"value": v, "quote": v, "page": 1} for k, v in values.items()}


async def read_invoice(s: Any, c: httpx.AsyncClient, model: Reader, values: dict[str, str], labels: Any = None) -> str:
    fid = await s.stored(form(values, labels or INVOICE_LABELS), name="inv.pdf", mime="application/pdf")
    model.queue.append(values)
    r = await c.post(
        "/v1/documents/extractions", json={"fileId": fid, "documentTypeId": "supplier_invoice"}, headers=OPS
    )
    return str(data(r)["id"])


async def test_a_suggestion_saved_as_a_version_reads_another_invoice_with_no_model_call(make: Make) -> None:
    model = Reader()
    s = make(model, Floor())
    async with s.client as c:
        data(await c.post("/v1/document-types", json=INVOICE_TYPE, headers=OPS), 201)
        first = await read_invoice(s, c, model, INVOICES[0])
        url = "/v1/document-types/supplier_invoice"
        suggested = data(await c.post(f"{url}/templates/suggest", json={"extractionIds": [first]}, headers=OPS))
        unchanged = data(await c.get(url, headers=OPS))
        body = {"fields": FIELDS, "templates": [suggested["template"]]}
        data(await c.post(f"{url}/versions", json=body, headers=OPS), 201)
        calls = model.calls
        fid = await s.stored(form(INVOICES[1], INVOICE_LABELS), name="next.pdf", mime="application/pdf")
        r = await c.post(
            "/v1/documents/extractions", json={"fileId": fid, "documentTypeId": "supplier_invoice"}, headers=OPS
        )
        got = data(r)
    [check] = suggested["checks"]
    assert check["matched"] and all(f["match"] for f in check["fields"].values()), check
    anchors = [a["text"] for p in suggested["template"]["pages"] for a in p["anchors"]]
    assert anchors == [label for label, _ in INVOICE_LABELS], anchors
    assert unchanged["latestVersion"] == 1, "a suggestion saves no version"
    assert (
        model.calls == calls and got["path"] == "template" and got["fields"]["vendor"]["value"] == "Northern Paper Co"
    )


async def test_offers_appear_at_five_checked_reads_of_one_layout_and_stop_once_a_template_reads_it(make: Make) -> None:
    model = Reader()
    s = make(model, Floor())
    url = "/v1/document-types/supplier_invoice"
    async with s.client as c:
        data(await c.post("/v1/document-types", json=INVOICE_TYPE, headers=OPS), 201)
        ids = [await read_invoice(s, c, model, v) for v in INVOICES[:4]]
        for v in INVOICES[4:6]:
            await read_invoice(s, c, model, v, STATEMENT_LABELS)
        four = data(await c.get(f"{url}/template-offers", headers=OPS))
        ids.append(await read_invoice(s, c, model, INVOICES[5]))
        five = data(await c.get(f"{url}/template-offers", headers=OPS))
        suggested = data(await c.post(f"{url}/templates/suggest", json={"extractionIds": ids}, headers=OPS))
        body = {"fields": FIELDS, "templates": [suggested["template"]]}
        data(await c.post(f"{url}/versions", json=body, headers=OPS), 201)
        after = data(await c.get(f"{url}/template-offers", headers=OPS))
    assert four == [], "four reads of the invoice and two statements offer nothing"
    [offer] = five
    assert offer["count"] == 5 and sorted(offer["extractionIds"]) == sorted(ids), offer
    assert all(ch["matched"] for ch in suggested["checks"]) and after == [], (suggested["checks"], after)


async def test_a_type_that_offers_at_three_reads_offers_at_three_and_keeps_it_on_its_next_version(make: Make) -> None:
    """The offer count was fixed at 5 in code; the owner's rule is 5, changeable per type (2026-10-18)."""
    model = Reader()
    s = make(model, Floor())
    url = "/v1/document-types/supplier_invoice"
    async with s.client as c:
        refused = await c.post("/v1/document-types", json={**INVOICE_TYPE, "offerAt": 1}, headers=OPS)
        made = data(await c.post("/v1/document-types", json={**INVOICE_TYPE, "offerAt": 3}, headers=OPS), 201)
        ids = [await read_invoice(s, c, model, v) for v in INVOICES[:3]]
        [offer] = data(await c.get(f"{url}/template-offers", headers=OPS))
        kept = data(await c.post(f"{url}/versions", json={"fields": FIELDS}, headers=OPS), 201)
    assert refused.status_code == 400 and made["versions"][0]["offerAt"] == 3, refused.text
    assert offer["count"] == 3 and sorted(offer["extractionIds"]) == sorted(ids), offer
    assert kept["offerAt"] == 3, "a version that does not name it keeps the type's count"


async def test_offers_group_stored_fingerprints_and_read_one_layout_per_offered_group(
    make: Make, engine: AsyncEngine
) -> None:
    """Listing offers read every one of the type's last 200 files' layouts again on each request: a read keeps its
    fingerprint, so a listing reads one layout per offered group; a read saved before fingerprints gets its own once."""
    model = Reader()
    s = make(model, Floor())
    url = "/v1/document-types/supplier_invoice/template-offers"
    layouts = 0
    layout_of = s.extractor.layout_of

    async def counted(who: Any, row: Any) -> dict[str, Any]:
        nonlocal layouts
        layouts += 1
        return await layout_of(who, row)

    s.extractor.layout_of = counted  # type: ignore[method-assign]
    async with s.client as c:
        data(await c.post("/v1/document-types", json=INVOICE_TYPE, headers=OPS), 201)
        ids = [await read_invoice(s, c, model, v) for v in INVOICES[:5]]
        layouts = 0
        [offer] = data(await c.get(url, headers=OPS))
        stored = layouts
        async with engine.begin() as conn:
            await conn.execute(
                sa.update(extractions).where(extractions.c.id.in_(ids[:2])).values(layout_fingerprint=None)
            )
        layouts = 0
        [again] = data(await c.get(url, headers=OPS))
        backfilled = layouts
        layouts = 0
        data(await c.get(url, headers=OPS))
    assert offer["count"] == 5 and again == offer, (offer, again)
    assert (stored, backfilled, layouts) == (1, 3, 1), (stored, backfilled, layouts)


async def test_a_read_of_another_type_or_not_the_teams_feeds_no_suggestion(make: Make) -> None:
    model = Reader()
    s = make(model, Floor())
    url = "/v1/document-types/supplier_invoice/templates/suggest"
    async with s.client as c:
        data(await c.post("/v1/document-types", json=INVOICE_TYPE, headers=OPS), 201)
        other = {**INVOICE_TYPE, "id": "bank_statement", "name": "Bank statement"}
        data(await c.post("/v1/document-types", json=other, headers=OPS), 201)
        fid = await s.stored(form(INVOICES[0], STATEMENT_LABELS), name="st.pdf", mime="application/pdf")
        model.queue.append(INVOICES[0])
        r = await c.post(
            "/v1/documents/extractions", json={"fileId": fid, "documentTypeId": "bank_statement"}, headers=OPS
        )
        statement = data(r)["id"]
        wrong_type = await c.post(url, json={"extractionIds": [statement]}, headers=OPS)
        unknown = await c.post(url, json={"extractionIds": ["ext_none"]}, headers=OPS)
    assert wrong_type.status_code == 400 and "was not read as supplier_invoice" in wrong_type.text, wrong_type.text
    assert unknown.status_code == 404, unknown.text


async def test_a_read_stored_with_a_date_boxed_with_its_label_still_suggests_a_clean_zone(
    make: Make, engine: AsyncEngine
) -> None:
    """A read stored before dates were boxed from their printed text has a box over "Due date 12/10/2026"; the
    suggestion finds the boxes again, so the next invoice's due date reads without the label."""
    model = Reader()
    s = make(model, Floor())
    url = "/v1/document-types/supplier_invoice"
    async with s.client as c:
        data(await c.post("/v1/document-types", json=INVOICE_TYPE, headers=OPS), 201)
        first = await read_invoice(s, c, model, INVOICES[0])
        async with engine.begin() as conn:
            row = (await conn.execute(sa.select(extractions.c.result).where(extractions.c.id == first))).scalar_one()
            result = json.loads(row)
            result["fields"]["due"]["boxes"] = [{"page": 1, "x": 0.1, "y": 0.24, "w": 0.5, "h": 0.02}]
            await conn.execute(
                sa.update(extractions).where(extractions.c.id == first).values(result=json.dumps(result))
            )
        suggested = data(await c.post(f"{url}/templates/suggest", json={"extractionIds": [first]}, headers=OPS))
        data(
            await c.post(f"{url}/versions", json={"fields": FIELDS, "templates": [suggested["template"]]}, headers=OPS),
            201,
        )
        fid = await s.stored(form(INVOICES[1], INVOICE_LABELS), name="next.pdf", mime="application/pdf")
        r = await c.post(
            "/v1/documents/extractions", json={"fileId": fid, "documentTypeId": "supplier_invoice"}, headers=OPS
        )
        got = data(r)
    assert got["path"] == "template" and got["fields"]["due"]["value"] == "2026-12-11", got["fields"]["due"]
