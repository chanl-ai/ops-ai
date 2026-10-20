"""Checks and the one targeted re-read (c-296), through the extraction API, by failure mode: a total that does not add
up saved as checked (F1); a failed field never retried, or the whole document asked again (F3); a re-read value taken
although it fails again (F4); a check naming a field the version lacks saved (F5); a template read's bad field sending
the whole file to the model (US4)."""

from __future__ import annotations

from typing import Any

import httpx

from .conftest import OPS, Make
from .test_extractions import Floor
from .test_templates import INVOICE_LABELS, OTHER, data, form, read, with_template

PAGE = b"Invoice INV-7 issued 10/01/2026\nSubtotal 100.00\nTax 13.00\nTotal 118.00\nDue 11/18/2026 or 41/18/2026\n"
FIELDS = [
    {"key": "invoice_no", "type": "text", "required": True},
    {"key": "subtotal", "type": "money"},
    {"key": "tax", "type": "money"},
    {"key": "total", "type": "money", "required": True},
    {"key": "due", "type": "date"},
]
SUM = {"id": "total_adds_up", "kind": "sum", "fields": ["subtotal", "tax"], "equals": "total"}


def said(value: str) -> dict[str, Any]:
    return {"value": value, "quote": value, "page": 1}


FIRST = {"invoice_no": said("INV-7"), "subtotal": said("100.00"), "tax": said("13.00"), "total": said("118.00"),
         "due": said("41/18/2026")}  # fmt: skip


class Model:
    """Answers each call from a queue, keeping what each was asked."""

    def __init__(self, *answers: dict[str, Any]) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[str, list[str]]] = []

    async def structured(self, system: str, user: str, schema: dict[str, Any], **kwargs: Any) -> Any:
        self.asked.append((str(kwargs.get("step")), sorted(schema["properties"])))
        if (usage := kwargs.get("usage")) is not None:
            usage.input_tokens, usage.output_tokens = usage.input_tokens + 40, usage.output_tokens + 6
        answer = self.answers.pop(0)
        return {k: v for k, v in answer.items() if k in schema["properties"]}


async def made(c: httpx.AsyncClient, checks: list[dict[str, Any]]) -> None:
    body = {"id": "bill", "name": "Bill", "fields": FIELDS, "checks": checks}
    data(await c.post("/v1/document-types", json=body, headers=OPS), 201)


async def extract(s: Any, c: httpx.AsyncClient) -> dict[str, Any]:
    fid = await s.stored(PAGE)
    return data(await c.post("/v1/documents/extractions", json={"fileId": fid, "documentTypeId": "bill"}, headers=OPS))


async def test_a_bad_date_is_re_read_alone_and_the_passing_value_kept(make: Make) -> None:
    model = Model(FIRST, {"due": said("11/18/2026")})
    s = make(model, Floor(0.5))
    async with s.client as c:
        await made(c, [])
        got = await extract(s, c)
    due = got["fields"]["due"]
    assert model.asked == [("extract", sorted(f["key"] for f in FIELDS)), ("extract:reread", ["due"])], model.asked
    assert (due["value"], due.get("reread"), due.get("rejected")) == ("2026-11-18", True, None), due


async def test_a_value_that_fails_again_goes_to_review_with_the_rule_named(make: Make) -> None:
    model = Model(FIRST, {"due": said("41/18/2026")})
    s = make(model, Floor(0.5))
    async with s.client as c:
        await made(c, [])
        got = await extract(s, c)
    due = got["fields"]["due"]
    assert (due["value"], due["needsReview"], due["rejected"], due["extractedValue"]) == (
        None,
        True,
        "type",
        "41/18/2026",
    )
    assert len(model.asked) == 2 and "due" in got["needsReview"], got


async def test_a_total_that_does_not_add_up_goes_to_review_with_its_check(make: Make) -> None:
    fine_date = {**FIRST, "due": said("11/18/2026")}
    model = Model(fine_date, {"subtotal": said("100.00"), "tax": said("13.00"), "total": said("118.00")})
    s = make(model, Floor(0.5))
    async with s.client as c:
        await made(c, [SUM])
        got = await extract(s, c)
    flagged = {k: got["fields"][k].get("rejected") for k in ("subtotal", "tax", "total")}
    assert flagged == dict.fromkeys(flagged, "check:total_adds_up") and model.asked[1] == (
        "extract:reread",
        ["subtotal", "tax", "total"],
    )
    assert got["outcome"] == "review" and got["fields"]["due"].get("rejected") is None, got


async def test_a_check_naming_a_field_the_version_lacks_is_refused(make: Make) -> None:
    s = make(Model(), Floor())
    async with s.client as c:
        body = {"id": "bill", "name": "Bill", "fields": FIELDS, "checks": [{**SUM, "equals": "grand_total"}]}
        r = await c.post("/v1/document-types", json=body, headers=OPS)
    assert r.status_code == 400 and "not fields of the version" in r.text, r.text


async def test_a_template_reads_bad_date_is_re_read_alone_and_the_read_stays_on_the_template(make: Make) -> None:
    model = Model({"due": said("12/15/2026")})
    s = make(model, Floor())
    async with s.client as c:
        await with_template(c)
        fid = await s.stored(
            form({**OTHER, "due": "13/45/2026"}, INVOICE_LABELS), name="bad.pdf", mime="application/pdf"
        )
        got = await read(c, fid)
    assert got["path"] == "template" and model.asked == [("extract:reread", ["due"])], (got.get("path"), model.asked)
    assert got["fields"]["due"]["value"] == "2026-12-15" and got["fields"]["due"]["reread"] is True
    # Its tokens are on the read, though the template path stays out of the estimate's average.
    assert got["rereadTokens"] == {"input": 40, "output": 6}, got.get("rereadTokens")
