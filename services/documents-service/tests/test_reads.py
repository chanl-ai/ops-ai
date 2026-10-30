"""Reading a document without a document type (c-535), by failure mode: a full-text read that calls a model or charges
the team; a proposed value with no quote, or with the model's own confidence instead of the checks'; a proposal asked
over the whole of a long scan; a read past its token ceiling that fails instead of stopping with what it read; a
budget or rate refusal from models-service read as the model being down; an unknown read accepted; and a saved
proposal that loses its file."""

from __future__ import annotations

import io
from typing import Any

import httpx
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas

from ops_documents.extraction import ModelsService

from .conftest import OPS, Make
from .test_document_types import Prices
from .test_extractions import GOOD, NOTICE, Floor, Models

PROPOSAL = {
    "name": "Invoice",
    "fields": [
        {"key": "invoice", "label": "Invoice number", "type": "text", "description": "The invoice's number"},
        {"key": "amount", "label": "Amount due", "type": "money", "description": "What the customer owes"},
    ],
}


class Prompts(Models):
    """Models that also keeps each call's user prompt, to see which pages a call was given."""

    def __init__(self, *answers: Any) -> None:
        super().__init__(*answers)
        self.prompts: list[str] = []

    async def structured(self, system: str, user: str, schema: dict[str, Any], **kw: Any) -> Any:
        self.prompts.append(user)
        return await super().structured(system, user, schema, **kw)


def pdf(*pages: str) -> bytes:
    """A PDF with one page per string, each line drawn where a scan would put it."""
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    for text in pages:
        for i, line in enumerate(text.splitlines()):
            c.drawString(72, LETTER[1] - 100 - 16 * i, line)
        c.showPage()
    c.save()
    return buf.getvalue()


THREE = (
    NOTICE.decode(),
    "Remittance advice\nPay to Northwind Components Ltd\nAccount 40 1188 2271\n",
    "Terms and conditions\nPayment is due within 45 days\nLate fees apply after the due date\n",
)


async def read(c: httpx.AsyncClient, file_id: str, **body: Any) -> httpx.Response:
    return await c.post("/v1/documents/extractions", json={"fileId": file_id, **body}, headers=OPS)


async def test_a_full_text_read_returns_every_page_in_order_and_calls_no_model(make: Make) -> None:
    models = Models()
    s = make(models, Floor())
    async with s.client as c:
        fid = await s.stored(pdf(*THREE), name="po.pdf", mime="application/pdf")
        r = await read(c, fid, read="text")
    body = r.json()["data"]
    assert r.status_code == 200 and body["status"] == "done", r.text
    assert [p["number"] for p in body["pages"]] == [1, 2, 3], body["pages"]
    assert "Invoice INV-2207" in body["pages"][0]["text"] and "Remittance advice" in body["pages"][1]["text"], body
    text = body["text"]
    assert text.index("Invoice INV-2207") < text.index("Remittance advice") < text.index("Terms and conditions"), text
    assert models.calls == [], "a full-text read reads the layout, never a model"


async def test_max_pages_reads_only_the_pages_asked_for(make: Make) -> None:
    s = make(Models(), Floor())
    async with s.client as c:
        fid = await s.stored(pdf(*THREE), name="po.pdf", mime="application/pdf")
        body = (await read(c, fid, read="text", maxPages=2)).json()["data"]
    assert [p["number"] for p in body["pages"]] == [1, 2] and "Terms and conditions" not in body["text"], body


async def test_a_proposed_read_asks_over_the_first_pages_then_scores_each_value_by_the_checks(make: Make) -> None:
    invented = {**GOOD, "invoice": {"value": "INV-9999", "quote": "Invoice INV-9999", "page": 1}}
    models = Prompts(PROPOSAL, invented)
    s = make(models, Floor(0.5))
    async with s.client as c:
        fid = await s.stored(pdf(*THREE), name="po.pdf", mime="application/pdf")
        r = await read(c, fid, read="propose", hint="a supplier invoice", proposePages=1)
    body = r.json()["data"]
    assert r.status_code == 200 and body["status"] == "done", r.text
    assert [s for s, _ in models.calls] == ["propose", "extract"], models.calls
    assert "Invoice INV-2207" in models.prompts[0] and "Terms and conditions" not in models.prompts[0], (
        "the proposal reads only the first proposePages pages"
    )
    assert "a supplier invoice" in models.prompts[0], "the hint reaches the proposal"
    assert body["proposal"]["name"] == "Invoice", body
    assert [f["key"] for f in body["proposal"]["fields"]] == ["invoice", "amount"], body["proposal"]
    amount, invoice = body["fields"]["amount"], body["fields"]["invoice"]
    assert amount["citation"]["quote"] == "Amount due: 1,250.00 CAD" and amount["citation"]["page"] == 1, amount
    # A quote the page does not hold scores 0, whatever the model said: the checks score proposed fields too.
    assert invoice["confidence"] == 0 and "invoice" in body["needsReview"], body


async def test_a_proposal_with_no_fields_ends_done_and_says_so(make: Make) -> None:
    models = Models({"name": "", "fields": []})
    s = make(models, Floor())
    async with s.client as c:
        body = (await read(c, await s.stored(NOTICE), read="propose")).json()["data"]
    assert body["status"] == "done" and body["proposal"]["fields"] == [], body
    assert [s for s, _ in models.calls] == ["propose"], "nothing is read with an empty proposal"


async def test_a_read_past_its_token_ceiling_stops_with_what_it_read(make: Make) -> None:
    models = Prompts({"invoice": GOOD["invoice"]})
    s = make(models, Floor(0.5))
    async with s.client as c:
        fid = await s.stored(pdf(*THREE), name="po.pdf", mime="application/pdf")
        # About 4 characters a token: the first page's 62 characters fit in 20 tokens, the first two pages do not.
        r = await read(c, fid, fields=[{"key": "invoice", "type": "text"}], maxTokens=20)
    body = r.json()["data"]
    assert r.status_code == 200 and body["status"] == "done", r.text
    assert body["partial"] is True and body["readPages"] == 1, body
    assert "Remittance advice" not in models.prompts[0], "pages past the ceiling are not sent"


def _refusing(status: int, code: str) -> ModelsService:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"success": False, "error": {"code": code, "message": code}})

    return ModelsService(httpx.AsyncClient(base_url="http://models", transport=httpx.MockTransport(answer)), "key")


async def test_a_spent_budget_and_a_busy_model_are_told_apart_from_a_model_that_is_down(make: Make) -> None:
    said: dict[str, Any] = {}
    for status, code in ((429, "key_budget_exhausted"), (429, "tenant_budget_exhausted"), (429, "rate_limited")):
        s = make(_refusing(status, code), Floor())
        async with s.client as c:
            body = (await read(c, await s.stored(NOTICE), fields=[{"key": "invoice", "type": "text"}])).json()["data"]
        error: dict[str, Any] = body.get("error") or {}
        said[code] = (body["status"], error.get("code"))
    assert said == {
        "key_budget_exhausted": ("failed", "budget_exhausted"),
        "tenant_budget_exhausted": ("failed", "budget_exhausted"),
        "rate_limited": ("failed", "model_rate_limited"),
    }, said


async def test_an_unknown_read_and_a_bad_ceiling_are_refused(make: Make) -> None:
    s = make(Models(), Floor())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        unknown = await read(c, fid, read="everything", fields=[{"key": "invoice", "type": "text"}])
        ceiling = await read(c, fid, read="text", maxPages=0)
    # Refused for what they asked, not because the request knows no such parameter.
    for r, names in ((unknown, ("fields", "text", "propose")), (ceiling, ("maxPages",))):
        error = r.json()["error"]
        assert r.status_code == 400 and error["code"] == "validation_failed", r.text
        assert all(n in error["message"] for n in names) and "Extra inputs" not in error["message"], error


async def test_saving_a_proposal_keeps_its_file_as_the_first_sample(make: Make) -> None:
    s = make(Models(), Floor(), Prices())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        body = {"id": "invoice", "name": "Invoice", "fields": PROPOSAL["fields"], "sampleFileId": fid}
        made = await c.post("/v1/document-types", json=body, headers=OPS)
    assert made.status_code == 201, made.text
    assert s.files.files[fid]["referenceCount"] == 1, "Files keeps the file the proposal was read from"
