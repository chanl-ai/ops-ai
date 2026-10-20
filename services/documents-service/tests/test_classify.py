"""Classify per file (c-249, model first), by failure mode: a detected file read with the wrong type's fields, or not
read at all (F1); an unknown or doubtful kind read anyway instead of going to a person (F2); a retried step paying for
a second classification (F3)."""

from __future__ import annotations

from typing import Any

import httpx

from .conftest import OPS, Make
from .test_document_types import READ, TYPE, Prices, data
from .test_extractions import NOTICE, Floor


class Models:
    """The model: a classification when asked for a typeId, else the invoice's fields."""

    def __init__(self, kind: str, confidence: float) -> None:
        self.kind, self.confidence = kind, confidence
        self.steps: list[str] = []

    async def structured(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        run: str,
        step: str,
        tenant: str,
        usage: Any = None,
        images: Any = (),
    ) -> Any:
        self.steps.append(step)
        if "typeId" in schema["properties"]:
            return {"typeId": self.kind, "confidence": self.confidence, "reason": "The page says Invoice."}
        return {k: v for k, v in READ.items() if k in schema["properties"]}


async def detect(c: httpx.AsyncClient, fid: str, key: str | None = None) -> dict[str, Any]:
    headers = {**OPS, **({"Idempotency-Key": key} if key else {})}
    return data(await c.post("/v1/documents/extractions", json={"fileId": fid, "detect": True}, headers=headers))


async def test_a_detected_file_is_read_with_the_kind_found(make: Make) -> None:
    models = Models("invoice_notice", 0.95)
    s = make(models, Floor(0.8), Prices())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        read = await detect(c, fid)
        asked = data(await c.post("/v1/documents/classifications", json={"fileId": fid}, headers=OPS))
    assert read["outcome"] in ("ok", "review") and read["documentType"] == {
        "id": "invoice_notice",
        "version": 1,
        "name": "Invoice notice",
    }, read
    assert read["classification"]["typeId"] == "invoice_notice" and read["fields"]["invoice"]["value"] == "INV-2207"
    assert (asked["typeId"], asked["needsReview"], asked["name"]) == ("invoice_notice", False, "Invoice notice"), asked
    assert models.steps == ["classify", "extract", "classify"]


async def test_an_unknown_or_doubtful_kind_goes_to_a_person_unread(make: Make) -> None:
    for kind, confidence in (("unknown", 0.9), ("invoice_notice", 0.5)):
        models = Models(kind, confidence)
        s = make(models, Floor(0.8), Prices())
        async with s.client as c:
            fid = await s.stored(NOTICE)
            made = await c.post("/v1/document-types", json=TYPE, headers=OPS)
            assert made.status_code in (201, 409), made.text  # the second pass shares the first's tenant
            read = await detect(c, fid)
        assert (read["status"], read["outcome"], read["needsReview"]) == ("done", "unknown", ["documentType"]), read
        assert read["fields"] == {} and read["classification"]["needsReview"] is True, read
        assert models.steps == ["classify"], f"{kind} was read anyway"


async def test_a_retried_detect_reads_the_first_answer(make: Make) -> None:
    models = Models("invoice_notice", 0.95)
    s = make(models, Floor(0.8), Prices())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        first = await detect(c, fid, key="run_1:read:0")
        again = await detect(c, fid, key="run_1:read:0")
    assert again["id"] == first["id"] and models.steps == ["classify", "extract"], models.steps
