"""Page images to the model (c-295), through the extraction API and the real models-service client over a faked
models-service, by failure mode: a member without documents.manage turning images on (US1); a team that never turned
the policy on, or whose policy cannot be read, sending pages anyway (US2); a version with images off sending them; a
text page whose fields all pass sending its page; a scan read without its page or a doubtful field re-read without its
crop (US3); an alias not cleared for images failing the read instead of reading on text-only (US4); an image call left
off the read (US5)."""

from __future__ import annotations

import json
from typing import Any, cast

import httpx
import pytest

from ops_documents.extraction import ModelsService, PlatformPageImages
from ops_identity import ServiceUnreachable
from ops_ingest.parsers.ocr import OcrUnavailableError, TesseractEngine

from .conftest import OPS, Make, Service
from .test_extractions import Floor
from .test_templates import FIELDS, INVOICE_LABELS, OTHER, data, form, scan

TYPE = {"id": "supplier_invoice", "name": "Supplier invoice", "fields": FIELDS}


class FakeModels:
    """models-service's completions: answers each field with OTHER's printed value, keeps every request, and refuses an
    image part with 403 images_not_cleared when the alias is not cleared."""

    def __init__(self, *, cleared: bool = True) -> None:
        self.cleared = cleared
        self.calls: list[tuple[str, int]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        content = body["messages"][-1]["content"]
        parts = cast(list[dict[str, Any]], content) if isinstance(content, list) else []
        images = sum(1 for p in parts if p.get("type") == "image_url")
        self.calls.append((request.headers["X-Step-Id"], images))
        if images and not self.cleared:
            error = {"code": "images_not_cleared", "message": "not cleared"}
            return httpx.Response(403, json={"success": False, "error": error})
        schema = body["tools"][0]["function"]["parameters"]
        answer = {k: {"value": OTHER[k], "quote": OTHER[k], "page": 1} for k in schema["properties"]}
        call = {"id": "c1", "type": "function", "function": {"name": "final_result", "arguments": json.dumps(answer)}}
        message = {"role": "assistant", "content": None, "tool_calls": [call]}
        return httpx.Response(
            200,
            json={
                "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )


class Policy:
    def __init__(self, on: bool) -> None:
        self.on = on
        self.asked = 0

    async def allowed(self, tenant: str, team: str) -> bool:
        self.asked += 1
        return self.on


def served(make: Make, models: FakeModels, policy: Any, role: str = "admin") -> Service:
    http = httpx.AsyncClient(transport=httpx.MockTransport(models.handle), base_url="http://models")
    s = make(ModelsService(http, "mk_test"), Floor(0.5), role=role)
    s.extractor.page_image_policy = policy
    return s


async def typed(c: httpx.AsyncClient, *, page_images: bool = True, fields: list[dict[str, Any]] = FIELDS) -> None:
    body = {**TYPE, "fields": fields, "pageImages": page_images}
    data(await c.post("/v1/document-types", json=body, headers=OPS), 201)


async def read(s: Service, c: httpx.AsyncClient, pdf: bytes, *, ocr: bool = False) -> dict[str, Any]:
    fid = await s.stored(pdf, name="invoice.pdf", mime="application/pdf")
    body = {"fileId": fid, "documentTypeId": "supplier_invoice", "ocr": ocr}
    return data(await c.post("/v1/documents/extractions", json=body, headers=OPS))


def needs_ocr() -> None:
    try:
        TesseractEngine()
    except OcrUnavailableError as e:
        pytest.skip(str(e))


async def test_turning_page_images_on_needs_documents_manage_and_a_later_version_keeps_it(make: Make) -> None:
    builder = served(make, FakeModels(), Policy(True), role="builder")
    async with builder.client as c:
        r = await c.post("/v1/document-types", json={**TYPE, "pageImages": True}, headers=OPS)
        assert (r.status_code, r.json()["error"]["code"]) == (403, "role_required"), r.text
        await typed(c, page_images=False)
        r = await c.post(
            "/v1/document-types/supplier_invoice/versions", json={"fields": FIELDS, "pageImages": True}, headers=OPS
        )
        assert r.status_code == 403, r.text
    admin = served(make, FakeModels(), Policy(True))
    async with admin.client as c:
        on = await c.post(
            "/v1/document-types/supplier_invoice/versions", json={"fields": FIELDS, "pageImages": True}, headers=OPS
        )
        assert data(on, 201)["pageImages"] is True
    again = served(make, FakeModels(), Policy(True), role="builder")
    async with again.client as c:
        kept = await c.post("/v1/document-types/supplier_invoice/versions", json={"fields": FIELDS}, headers=OPS)
        assert data(kept, 201)["pageImages"] is True, "carried forward without documents.manage"
        off = await c.post(
            "/v1/document-types/supplier_invoice/versions", json={"fields": FIELDS, "pageImages": False}, headers=OPS
        )
        assert data(off, 201)["pageImages"] is False


async def test_a_scan_goes_with_its_page_when_type_team_and_alias_allow_it_and_the_call_is_on_the_read(
    make: Make,
) -> None:
    needs_ocr()
    models = FakeModels()
    s = served(make, models, Policy(True))
    async with s.client as c:
        await typed(c)
        got = await read(s, c, scan(form(OTHER, INVOICE_LABELS)), ocr=True)
    assert got["status"] == "done" and models.calls[0] == ("extract", 1), models.calls
    assert got["imageCalls"][0] == {"step": "extract", "pages": [1], "images": 1, "alias": "extract"}, got
    assert len(got["imageCalls"]) == sum(1 for _, n in models.calls if n), "every image call is on the read"


@pytest.mark.parametrize("gate", ["type off", "team off", "policy unread"])
async def test_no_page_leaves_unless_every_gate_allows_it(make: Make, gate: str) -> None:
    needs_ocr()

    class Unreachable:
        async def get(self, path: str) -> Any:
            raise ServiceUnreachable("platform-service down")

    policy: Any = {
        "type off": Policy(True),
        "team off": Policy(False),
        "policy unread": PlatformPageImages(lambda tenant, team: cast(Any, Unreachable())),
    }[gate]
    models = FakeModels()
    s = served(make, models, policy)
    async with s.client as c:
        await typed(c, page_images=gate != "type off")
        got = await read(s, c, scan(form(OTHER, INVOICE_LABELS)), ocr=True)
    assert got["status"] == "done" and models.calls and all(n == 0 for _, n in models.calls), models.calls
    assert "imageCalls" not in got


async def test_a_text_page_whose_fields_all_pass_sends_no_image_and_never_asks_the_policy(make: Make) -> None:
    models, policy = FakeModels(), Policy(True)
    s = served(make, models, policy)
    async with s.client as c:
        await typed(c)
        got = await read(s, c, form(OTHER, INVOICE_LABELS))
    assert models.calls == [("extract", 0)] and policy.asked == 0 and "imageCalls" not in got, (models.calls, got)


async def test_a_field_failing_its_rule_on_a_text_page_is_re_read_with_a_crop_of_its_line(make: Make) -> None:
    models = FakeModels()
    s = served(make, models, Policy(True))
    ruled = [{**f, "pattern": "^ACC-"} if f["key"] == "invoice_no" else f for f in FIELDS]
    async with s.client as c:
        await typed(c, fields=ruled)
        got = await read(s, c, form(OTHER, INVOICE_LABELS))
    assert models.calls == [("extract", 0), ("extract:reread", 1)], models.calls
    assert got["imageCalls"] == [{"step": "extract:reread", "pages": [1], "images": 1, "alias": "extract"}], got


async def test_an_alias_not_cleared_for_images_reads_on_text_only_and_says_why(make: Make) -> None:
    needs_ocr()
    models = FakeModels(cleared=False)
    s = served(make, models, Policy(True))
    async with s.client as c:
        await typed(c)
        got = await read(s, c, scan(form(OTHER, INVOICE_LABELS)), ocr=True)
    assert got["status"] == "done" and models.calls[:2] == [("extract", 1), ("extract", 0)], models.calls
    assert "not cleared for page images" in got["imageRefused"] and "imageCalls" not in got, got
