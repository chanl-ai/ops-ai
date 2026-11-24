"""A model reply that is cut off, empty, declined or filtered, by failure mode: saved as empty fields, or asked again
for nobody under the same key; a retry skipped or calls stacked past the cap; a declined reply retried, mislabelled or
its words leaked. models-service is faked at HTTP, so the reading service's own model client reads each reply."""

from __future__ import annotations

import json
from typing import Any, cast

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.extraction import ModelsService
from ops_documents.store.extractions import service_outbox

from .conftest import OPS, Make, tenant_outbox
from .test_document_types import TYPE, data
from .test_extractions import FIELDS, GOOD, NOTICE, Floor
from .test_page_images import FakeModels, Policy, served, typed
from .test_page_images import read as read_typed
from .test_templates import FIELDS as FIELDS_PAGED
from .test_templates import INVOICE_LABELS, OTHER, form

USAGE = {"prompt_tokens": 900, "completion_tokens": 4000}


def _reply(message: dict[str, Any], finish: str) -> dict[str, Any]:
    return {
        "choices": [{"index": 0, "message": {"role": "assistant", **message}, "finish_reason": finish}],
        "usage": USAGE,
    }


def whole(answer: dict[str, Any]) -> dict[str, Any]:
    call = {"id": "c1", "type": "function", "function": {"name": "final_result", "arguments": json.dumps(answer)}}
    return _reply({"content": None, "tool_calls": [call]}, "tool_calls")


def cut() -> dict[str, Any]:
    call = {"id": "c1", "type": "function", "function": {"name": "final_result", "arguments": '{"invoice": {"val'}}
    return _reply({"content": None, "tool_calls": [call]}, "length")


def declined(words: str) -> dict[str, Any]:
    return _reply({"content": None, "refusal": words}, "stop")


def plain(words: str) -> dict[str, Any]:
    return _reply({"content": words}, "stop")


class Replies:
    """models-service answering each completion with the next reply, keeping every request body it was sent."""

    def __init__(self, *replies: dict[str, Any]) -> None:
        self.replies = list(replies)
        self.sent: list[dict[str, Any]] = []
        self.steps: list[str] = []

    def service(self) -> ModelsService:
        def answer(request: httpx.Request) -> httpx.Response:
            self.sent.append(json.loads(request.content))
            self.steps.append(request.headers["x-step-id"])
            return httpx.Response(200, json=self.replies.pop(0) if self.replies else whole(GOOD))

        return ModelsService(httpx.AsyncClient(base_url="http://models", transport=httpx.MockTransport(answer)), "key")


class Masked:
    async def masks(self, tenant: str, team: str) -> bool:
        return True


async def _read(c: httpx.AsyncClient, file_id: str, key: str | None = None, **body: Any) -> dict[str, Any]:
    headers = {**OPS, **({"Idempotency-Key": key} if key else {})}
    r = await c.post("/v1/documents/extractions", json={"fileId": file_id, **body}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_a_cut_off_reply_is_not_read_and_stays_the_answer_for_its_key(make: Make) -> None:
    models = Replies(cut(), cut())
    s = make(models.service(), Floor())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        first = await _read(c, fid, "batch-7:NWF-88213", fields=FIELDS)
        again = await _read(c, fid, "batch-7:NWF-88213", fields=FIELDS)
    assert (first["status"], first["outcome"]) == ("done", "incomplete"), first
    assert first["incomplete"]["reason"] == "cut_off", first
    for key in ("invoice", "amount"):
        field = first["fields"][key]
        assert field["value"] is None and field["notRead"] == "cut_off" and field["needsReview"], field
    assert models.steps == ["extract", "extract:retry"], "one ask, one retry, and none for the same key again"
    assert again["id"] == first["id"] and again["outcome"] == "incomplete", again


async def test_a_reply_cut_off_once_is_asked_again_unchanged_with_an_output_limit(make: Make) -> None:
    models = Replies(cut(), whole(GOOD))
    s = make(models.service(), Floor())
    async with s.client as c:
        body = await _read(c, await s.stored(NOTICE), fields=FIELDS)
    assert body["outcome"] == "ok", body
    assert models.steps == ["extract", "extract:retry"], models.steps
    assert models.sent[0]["messages"] == models.sent[1]["messages"], "the retry asks the same thing"
    assert all(isinstance(b.get("max_completion_tokens"), int) for b in models.sent), models.sent


async def test_a_declined_reply_is_never_retried_and_its_words_are_masked_but_an_empty_one_is(
    make: Make, engine: AsyncEngine
) -> None:
    words = "I can't read the record of the customer with SSN 123-45-6789."
    said: dict[str, Any] = {}
    # A reply with words but no answer form is empty, and is asked again like a cut-off one; a declined one is not.
    talk = plain("Here is the invoice you sent.")
    for kind, replies in (("declined", [declined(words)]), ("empty", [talk, talk])):
        models = Replies(*replies)
        s = make(models.service(), Floor())
        s.extractor.masking = Masked()
        async with s.client as c:
            body = await _read(c, await s.stored(NOTICE), fields=FIELDS)
        said[kind] = (body["outcome"], body["incomplete"]["reason"], models.steps)
        if kind == "declined":
            refusal = body["incomplete"]["refusal"]
            assert "123-45-6789" not in refusal and refusal.startswith("I can't read"), refusal
            q = sa.select(service_outbox.c.payload).where(service_outbox.c.event_key == body["id"])
            events = await tenant_outbox(engine, s.tenant, q)
            assert events and words not in json.dumps(events, default=str), events
    assert said == {
        "declined": ("incomplete", "declined", ["extract"]),
        "empty": ("incomplete", "empty", ["extract", "extract:retry"]),
    }, said


async def test_a_cut_off_proposal_fails_and_a_cut_off_detect_goes_to_a_person(make: Make) -> None:
    proposing, detecting = Replies(cut()), Replies(cut())
    s, d = make(proposing.service(), Floor()), make(detecting.service(), Floor())
    async with s.client as c:
        proposed = await _read(c, await s.stored(NOTICE), read="propose")
    async with d.client as c:
        data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
        detected = await _read(c, await d.stored(NOTICE), detect=True)
    assert (proposed["status"], proposed["error"]["code"]) == ("failed", "reply_incomplete"), proposed
    assert (detected["status"], detected["outcome"]) == ("done", "unknown"), detected
    assert detected["classification"]["reason"] == "The model gave no answer.", detected


class CutReread(FakeModels):
    """Answers the first read whole and cuts the re-read off at its limit, keeping each request's image parts."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        content = body["messages"][-1]["content"]
        parts = cast(list[dict[str, Any]], content) if isinstance(content, list) else []
        self.parts += [p for p in parts if p.get("type") == "image_url"]
        if request.headers["X-Step-Id"] == "extract:reread":
            self.calls.append(("extract:reread", 0))
            return httpx.Response(200, json=cut())
        return super().handle(request)


async def test_a_cut_off_re_read_keeps_the_first_values_and_says_so(make: Make) -> None:
    models = CutReread()
    s = served(make, models, Policy(True))
    ruled = [{**f, "pattern": "^ACC-"} if f["key"] == "invoice_no" else f for f in FIELDS_PAGED]
    async with s.client as c:
        await typed(c, fields=ruled)
        got = await read_typed(s, c, form(OTHER, INVOICE_LABELS))
    assert got["outcome"] == "review" and "invoice_no" in got["needsReview"], got
    assert got["fields"]["invoice_no"]["extractedValue"] == OTHER["invoice_no"], "the first value stays"
    assert got["rereadIncomplete"] == "cut_off", got
    assert models.parts and all(p["image_url"]["detail"] == "high" for p in models.parts), models.parts
