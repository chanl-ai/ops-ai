"""Layout templates through the extraction API (c-253), on non-levy forms so nothing rests on one document type: an
invoice read from its template with no model call (F1), a bank statement of another layout taking the model path with
the miss recorded (F2), a shifted scan of the invoice read through OCR (F3), the token estimate left alone by template
reads (F5), and a template naming a field the version lacks refused (F6). Forms are printed here from one master."""

from __future__ import annotations

import io
from typing import Any

import httpx
import pdfplumber
import pytest
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas

from ops_extract.boxes import runs, tokens, union
from ops_extract.layout import build_layout
from ops_ingest.parsers.ocr import OcrUnavailableError, TesseractEngine

from .conftest import OPS, Make
from .test_extractions import Floor

INVOICE_LABELS = [("Invoice number", "invoice_no"), ("Vendor", "vendor"), ("Total due", "total"), ("Due date", "due")]
STATEMENT_LABELS = [
    ("Account", "invoice_no"),
    ("Holder", "vendor"),
    ("Closing balance", "total"),
    ("Period end", "due"),
]
MASTER = {"invoice_no": "INV-10021", "vendor": "Harbour Supplies Ltd", "total": "$1,250.00", "due": "11/30/2026"}
OTHER = {"invoice_no": "INV-20877", "vendor": "Northern Paper Co", "total": "$318.40", "due": "12/15/2026"}
FIELDS = [
    {"key": "invoice_no", "label": "Invoice number", "type": "text", "required": True},
    {"key": "vendor", "label": "Vendor", "type": "text", "required": True},
    {"key": "total", "label": "Total due", "type": "money", "required": True},
    {"key": "due", "label": "Due date", "type": "date"},
]


def form(values: dict[str, str], labels: list[tuple[str, str]], *, title: str = "INVOICE", dx: float = 0) -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72 + dx, LETTER[1] - 70 - dx, title)
    c.setFont("Helvetica", 12)
    for i, (label, key) in enumerate(labels):
        y = LETTER[1] - 130 - 32 * i - dx
        c.drawString(72 + dx, y, label)
        c.drawString(240 + dx, y, values[key])
    c.save()
    return buf.getvalue()


def scan(pdf: bytes) -> bytes:
    """The page rasterised into an image-only PDF, as a scanner gives it."""
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        image = doc.pages[0].to_image(resolution=200).original.convert("L")
    out = io.BytesIO()
    image.save(out, "PDF", resolution=200.0)
    return out.getvalue()


def template_from(pdf: bytes) -> dict[str, Any]:
    """Anchors at the master's labels and zones around its values, as c-254 will infer them."""
    words = [w for w in build_layout(pdf, filename="m.pdf")["words"] if w["page"] == 1]
    anchors: list[dict[str, Any]] = []
    zones: list[dict[str, Any]] = []
    for label, key in INVOICE_LABELS:
        anchors.append({"text": label, "box": union(next(runs(words, tokens(label))))})
        x0, top, x1, bottom = union(next(runs(words, tokens(MASTER[key]))))
        zones.append({"field": key, "box": [x0 - 0.01, top - 0.006, min(x1 + 0.2, 0.99), bottom + 0.006]})
    return {"id": "tpl_invoice_a", "pages": [{"page": 1, "anchors": anchors, "zones": zones}]}


INVOICE_TYPE = {"id": "supplier_invoice", "name": "Supplier invoice", "fields": FIELDS}


class NoModel:
    """Fails the test when a template read reaches the model."""

    def __init__(self) -> None:
        self.calls = 0

    async def structured(self, system: str, user: str, schema: dict[str, Any], **kwargs: Any) -> Any:
        self.calls += 1
        answer = {
            "invoice_no": {"value": "ACC-1", "quote": "ACC-1", "page": 1},
            "vendor": {"value": None, "quote": None, "page": None},
            "total": {"value": None, "quote": None, "page": None},
            "due": {"value": None, "quote": None, "page": None},
        }
        return {k: v for k, v in answer.items() if k in schema["properties"]}


def data(r: httpx.Response, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


async def with_template(c: httpx.AsyncClient) -> None:
    body = {**INVOICE_TYPE, "templates": [template_from(form(MASTER, INVOICE_LABELS))]}
    data(await c.post("/v1/document-types", json=body, headers=OPS), 201)


async def read(c: httpx.AsyncClient, fid: str, **body: Any) -> dict[str, Any]:
    r = await c.post(
        "/v1/documents/extractions", json={"fileId": fid, "documentTypeId": "supplier_invoice", **body}, headers=OPS
    )
    return data(r)


async def test_an_invoice_from_the_known_form_reads_from_its_zones_with_no_model_call(make: Make) -> None:
    models = NoModel()
    s = make(models, Floor())
    async with s.client as c:
        await with_template(c)
        fid = await s.stored(form(OTHER, INVOICE_LABELS), name="inv.pdf", mime="application/pdf")
        got = await read(c, fid)
    assert models.calls == 0 and (got["path"], got["templateId"]) == ("template", "tpl_invoice_a"), got
    values = {k: v["value"] for k, v in got["fields"].items()}
    assert values == {"invoice_no": "INV-20877", "vendor": "Northern Paper Co", "total": 318.4, "due": "2026-12-15"}
    assert all(v["boxes"] and v["confidence"] > 0.8 for v in got["fields"].values()), got["fields"]
    assert await s.extractor.store.tokens_per_call("supplier_invoice") is None, "F5: no measured tokens"


async def test_a_statement_of_another_layout_takes_the_model_path_with_the_miss(make: Make) -> None:
    models = NoModel()
    s = make(models, Floor())
    async with s.client as c:
        await with_template(c)
        fid = await s.stored(form(OTHER, STATEMENT_LABELS, title="STATEMENT"), name="st.pdf", mime="application/pdf")
        got = await read(c, fid)
    miss = got["templateMiss"]
    assert models.calls == 1 and got["path"] == "model" and "templateId" not in got, got
    assert miss["templateId"] == "tpl_invoice_a" and "Invoice number" in miss["missingAnchors"] and miss["score"] < 0.8


async def test_a_shifted_scan_of_the_invoice_reads_through_ocr_from_its_zones(make: Make) -> None:
    try:
        TesseractEngine()
    except OcrUnavailableError as e:
        pytest.skip(str(e))
    models = NoModel()
    s = make(models, Floor(0.5))
    async with s.client as c:
        await with_template(c)
        fid = await s.stored(scan(form(OTHER, INVOICE_LABELS, dx=8)), name="scan.pdf", mime="application/pdf")
        got = await read(c, fid, ocr=True)
    assert models.calls == 0 and got["path"] == "template", got
    assert got["fields"]["invoice_no"]["value"] == "INV-20877" and got["fields"]["total"]["value"] == 318.4, got


async def test_a_template_naming_a_field_the_version_lacks_is_refused(make: Make) -> None:
    s = make(NoModel(), Floor())
    bad = template_from(form(MASTER, INVOICE_LABELS))
    bad["pages"][0]["zones"].append({"field": "iban", "box": [0.1, 0.1, 0.2, 0.2]})
    async with s.client as c:
        r = await c.post("/v1/document-types", json={**INVOICE_TYPE, "templates": [bad]}, headers=OPS)
    assert r.status_code == 400 and "not a field of the version" in r.text, r.text


async def test_a_posted_rebuild_flag_does_not_let_a_zone_name_a_field_the_version_lacks(make: Make) -> None:
    """needsRebuild is set only on a template carried to a version that dropped a field; posted, it would let a template
    naming any field through unchecked."""
    s = make(NoModel(), Floor())
    bad = template_from(form(MASTER, INVOICE_LABELS))
    bad["pages"][0]["zones"].append({"field": "iban", "box": [0.1, 0.1, 0.2, 0.2]})
    async with s.client as c:
        r = await c.post("/v1/document-types", json={**INVOICE_TYPE, "templates": [bad | {"needsRebuild": True}]})
    assert r.status_code == 400 and "not a field of the version" in r.text, r.text


async def test_a_date_printed_impossible_is_read_from_its_zone_but_saved_with_no_value_and_sent_to_review(
    make: Make,
) -> None:
    """The template reads what the form prints; the date check rejects 13/45/2026, so it is never saved as found. The
    one re-read of that field (c-296) finds nothing better, so it stays in review."""
    models = NoModel()
    s = make(models, Floor())
    async with s.client as c:
        await with_template(c)
        misprinted = {**OTHER, "due": "13/45/2026"}
        fid = await s.stored(form(misprinted, INVOICE_LABELS), name="bad.pdf", mime="application/pdf")
        got = await read(c, fid)
    due = got["fields"]["due"]
    assert models.calls == 1 and got["path"] == "template", got
    assert (due["value"], due["needsReview"], due["extractedValue"]) == (None, True, "13/45/2026"), due


async def test_a_new_version_carries_templates_forward_and_flags_one_reading_a_dropped_field(make: Make) -> None:
    """A version made without naming templates keeps the ones a person saved; one reading a field the version no longer
    has is flagged for a rebuild and never matched; templates given explicitly replace them."""
    models = NoModel()
    s = make(models, Floor())
    url = "/v1/document-types/supplier_invoice/versions"
    async with s.client as c:
        await with_template(c)
        kept = data(await c.post(url, json={"fields": FIELDS}, headers=OPS), 201)
        fid = await s.stored(form(OTHER, INVOICE_LABELS), name="inv.pdf", mime="application/pdf")
        by_template = await read(c, fid)
        no_due = [f for f in FIELDS if f["key"] != "due"]
        flagged = data(await c.post(url, json={"fields": no_due}, headers=OPS), 201)
        after = await read(c, fid)
        cleared = data(await c.post(url, json={"fields": FIELDS, "templates": []}, headers=OPS), 201)
    assert [t["id"] for t in kept["templates"]] == ["tpl_invoice_a"] and "needsRebuild" not in kept["templates"][0]
    assert by_template["path"] == "template", by_template
    assert flagged["templates"][0]["needsRebuild"] is True, flagged["templates"]
    assert after["path"] == "model" and models.calls == 1, after
    assert cleared["templates"] == [], cleared
