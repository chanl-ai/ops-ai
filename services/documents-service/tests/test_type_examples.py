"""Corrections teach later reads of their document type (c-297), through the extraction and document-type APIs, by
failure mode: a correction in one team teaching another team's reads; a wrong correction still taught after removal;
prompts growing without bound as corrections pile up; a person reading a full SSN in the examples list, in its line or
its corrected value; the same field corrected twice teaching both values; stored examples growing without bound; a
deleted file's printed lines living on in the examples its corrections taught; and a read that cited the wrong line
teaching that line as where the corrected value is printed."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ops_documents.store import extractions
from ops_identity import dev_service_signer, mint_service_token

from .conftest import OPS, Make, Service
from .test_extractions import Floor

FIELDS = [
    {"key": "invoice_no", "label": "Invoice number", "type": "text", "required": True},
    {"key": "payer_ssn", "label": "Payer SSN", "type": "text"},
]
TYPE = {"id": "bill", "name": "Bill", "fields": FIELDS}


def page(n: int) -> bytes:
    return f"Invoice no INV-{n:04d}\nPayer SSN 123-45-6789\n".encode()


class Model:
    """Reads each field as printed (the invoice number with its prefix left on, so a person corrects it) and keeps
    every prompt it was given."""

    def __init__(self) -> None:
        self.users: list[str] = []

    async def structured(self, system: str, user: str, schema: dict[str, Any], **kwargs: Any) -> Any:
        self.users.append(user)
        number = next(w for w in user.split("Document:")[1].split() if w.startswith("INV-"))
        answer = {
            "invoice_no": {"value": f"no {number}", "quote": f"Invoice no {number}", "page": 1},
            "payer_ssn": {"value": "123-45-6789", "quote": "Payer SSN 123-45-6789", "page": 1},
        }
        return {k: v for k, v in answer.items() if k in schema["properties"]}


class Masking:
    def __init__(self, on: bool) -> None:
        self.on = on

    async def masks(self, tenant: str, team: str) -> bool:
        return self.on


def data(r: httpx.Response, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"] if status != 204 else None


async def read(s: Service, c: httpx.AsyncClient, n: int) -> dict[str, Any]:
    fid = await s.stored(page(n), name=f"bill-{n}.txt")
    return data(await c.post("/v1/documents/extractions", json={"fileId": fid, "documentTypeId": "bill"}, headers=OPS))


async def correct(c: httpx.AsyncClient, eid: str, key: str, value: Any) -> None:
    data(await c.patch(f"/v1/documents/extractions/{eid}/fields/{key}", json={"value": value}, headers=OPS))


async def examples(c: httpx.AsyncClient, headers: dict[str, str] = OPS) -> httpx.Response:
    return await c.get("/v1/document-types/bill/examples", headers=headers)


async def test_a_correction_becomes_one_example_its_later_reads_carry_until_it_is_removed(make: Make) -> None:
    model = Model()
    s = make(model, Floor(0.5))
    async with s.client as c:
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        first = await read(s, c, 1)
        await correct(c, first["id"], "invoice_no", "INV-0001x")
        await correct(c, first["id"], "invoice_no", "INV-0001")
        [example] = data(await examples(c))
        await read(s, c, 2)
        taught = model.users[-1]
        data(await c.delete(f"/v1/document-types/bill/examples/{example['id']}", headers=OPS), 204)
        await read(s, c, 3)
        untaught = model.users[-1]
        elsewhere = await examples(c, {"X-Team-Id": "team_fraud"})
    assert (example["field"], example["line"], example["value"]) == ("invoice_no", "Invoice no INV-0001", "INV-0001")
    assert 'invoice_no: printed "Invoice no INV-0001" is "INV-0001"' in taught, taught
    assert "INV-0001x" not in taught, "a field corrected twice on one read teaches its last value"
    assert "printed" not in untaught, "a removed example is no longer given"
    assert elsewhere.status_code == 404, "another team sees none of this team's type"


async def test_a_read_carries_three_examples_a_field_and_the_list_masks_what_the_prompt_keeps(make: Make) -> None:
    model = Model()
    s = make(model, Floor(0.5))
    async with s.client as c:
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        got: dict[str, Any] = {}
        for n in range(1, 6):
            got = await read(s, c, n)
            await correct(c, got["id"], "invoice_no", f"INV-{n:04d}")
        await correct(c, str(got["id"]), "payer_ssn", "123-45-6789")
        again = await read(s, c, 7)
        await correct(c, again["id"], "payer_ssn", "123-45-6789")
        listed = data(await examples(c))
        await read(s, c, 8)
        prompt = model.users[-1]
        s.extractor.masking = Masking(on=False)
        shown = data(await examples(c))
    assert sum(1 for line in prompt.splitlines() if line.startswith("- invoice_no: printed")) == 3, prompt
    assert "INV-0005" in prompt and "INV-0001" not in prompt, "the newest three of a field are given"
    ssn = [e for e in listed if e["field"] == "payer_ssn"]
    assert len(ssn) == 1, "the same field, line and value from another read adds nothing"
    assert ssn[0]["line"] == "Payer SSN [SSN]" and ssn[0]["value"] == "[SSN]", ssn
    assert "123-45-6789" in prompt, "the model is given the example as printed"
    real = next(e for e in shown if e["field"] == "payer_ssn")
    assert (real["line"], real["value"]) == ("Payer SSN 123-45-6789", "123-45-6789")


async def test_a_field_keeps_its_newest_examples_and_a_purged_files_examples_go(
    make: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(extractions, "EXAMPLES_KEPT_PER_FIELD", 2)
    s = make(Model(), Floor(0.5))
    service = mint_service_token(
        dev_service_signer(),
        service="agents",
        audience="documents",
        tenant_id=s.tenant,
        scopes=["documents:delete"],
        team_id="team_ops",
    )
    async with s.client as c:
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        reads: list[dict[str, Any]] = []
        for n in range(1, 4):
            reads.append(await read(s, c, n))
            await correct(c, reads[-1]["id"], "invoice_no", f"INV-{n:04d}")
        kept = [e["value"] for e in data(await examples(c))]
        s.files.files.pop(reads[2]["fileId"])
        purge = {"fileId": reads[2]["fileId"]}
        data(await c.post("/v1/documents/purge", json=purge, headers={"Authorization": f"Bearer {service}"}))
        left = [e["value"] for e in data(await examples(c))]
    assert kept == ["INV-0003", "INV-0002"], "a field keeps only its newest examples"
    assert left == ["INV-0002"], "a deleted file's example goes with its reads"


async def test_a_correction_the_cited_line_does_not_show_teaches_nothing(make: Make) -> None:
    s = make(Model(), Floor(0.5))
    async with s.client as c:
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        got = await read(s, c, 1)
        await correct(c, got["id"], "invoice_no", "INV-9999")
        await correct(c, got["id"], "payer_ssn", "987-65-4321")
        listed = data(await examples(c))
    assert listed == [], "a value its cited line does not show is not taught as printed there"
