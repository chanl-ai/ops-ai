"""Picture reading, by failure mode: a page with no text stays empty although a model could describe it; a page with
text is sent to the model anyway; a described page is sent again on the next ask; a long file of pictures runs past
its limit with nothing saying where it stopped; a picture leaves the service although the team's policy says no; and
a refused model call fails the whole reading instead of leaving that one page unread with the reason."""

from __future__ import annotations

import asyncio
import io
import shutil
from datetime import timedelta
from typing import Any

import httpx
import pytest
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from ops_documents.picture_reading import PictureReading
from ops_service_kit.model_calls import ModelCallError

from .conftest import OPS, Make
from .test_extractions import Floor, Models

DIAGRAM = "Three boxes, Mobile app, Intake service and Event queue, joined left to right by arrows."


def _diagram() -> ImageReader:
    """Boxes and arrows with no words, the way an architecture slide is often drawn."""
    img = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(img)
    for x in (60, 340, 620):
        draw.rectangle([x, 200, x + 200, 300], outline="black", width=3)
    draw.line([260, 250, 340, 250], fill="black", width=3)
    draw.line([540, 250, 620, 250], fill="black", width=3)
    out = io.BytesIO()
    img.save(out, "PNG")
    out.seek(0)
    return ImageReader(out)


def _labelled() -> ImageReader:
    """The same diagram with its boxes named in pixels, which OCR reads as a handful of words."""
    img = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(img)
    for x, label in ((60, "Mobile app"), (340, "Intake service"), (620, "Event queue")):
        draw.rectangle([x, 200, x + 200, 300], outline="black", width=3)
        draw.text((x + 15, 235), label, fill="black", font_size=26)
    out = io.BytesIO()
    img.save(out, "PNG")
    out.seek(0)
    return ImageReader(out)


def pdf(*pages: str) -> bytes:
    """One page per entry: "text" draws a sentence, "picture" only the diagram."""
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    for kind in pages:
        if kind == "text":
            c.drawString(72, 700, "Claims intake review: the event queue went live in three regions.")
        else:
            c.drawImage(_labelled() if kind == "labelled" else _diagram(), 72, 300, width=450, height=250)  # pyright: ignore[reportUnknownMemberType]
        c.showPage()
    c.save()
    return buf.getvalue()


class Seeing:
    """The model edge: answers each page picture with a description, or refuses with a models-service code."""

    def __init__(self, refuse: str | None = None, *, times: int | None = None, crash_at: int | None = None) -> None:
        # `times`: refuse only the first so many calls; `crash_at`: that call fails as a process dying mid-reading.
        self.refuse, self.times, self.crash_at = refuse, times, crash_at
        self.calls: list[dict[str, Any]] = []

    async def structured(
        self, system: str, user: str, schema: dict[str, Any], *, tenant: str, step: str, **kw: Any
    ) -> Any:
        self.calls.append(kw)
        if self.crash_at == len(self.calls):
            raise RuntimeError("the process stopped")
        if self.refuse and (self.times is None or len(self.calls) <= self.times):
            raise ModelCallError("refused", code=self.refuse, status=403)
        return {"text": "", "description": DIAGRAM}


class Policy:
    def __init__(self, on: bool = True) -> None:
        self.on = on

    async def allowed(self, tenant: str, team: str) -> bool:
        return self.on


PICTURES = {"ocr": "off", "pictureSensitivity": "internal"}


async def read_all(
    s: Any, c: httpx.AsyncClient, fid: str, ocr: str = "off", sensitivity: str = "internal"
) -> dict[str, Any]:
    """A knowledge read: asks for page pictures at the item's sensitivity."""
    asked = {"ocr": ocr, "pictureSensitivity": sensitivity}
    await c.post("/v1/documents/readings", json={"fileId": fid, **asked}, headers=OPS)
    await s.extractor.readings.drain()
    got = await c.get(f"/v1/documents/readings/{fid}", params=asked, headers=OPS)
    return got.json()["data"]


async def test_a_picture_page_is_described_once_and_a_text_page_is_not_sent(make: Make) -> None:
    model = Seeing()
    s = make(Models(), Floor(), pictures=PictureReading(model, Policy()))
    async with s.client as c:
        fid = await s.stored(pdf("text", "picture"), name="review.pdf", mime="application/pdf")
        body = await read_all(s, c, fid)
        again = await c.post(
            "/v1/documents/readings", json={"fileId": fid, "ocr": "off", "pictureSensitivity": "internal"}, headers=OPS
        )
        plain = await c.post("/v1/documents/readings", json={"fileId": fid, "ocr": "off"}, headers=OPS)
    assert body["status"] == "done", body
    text, picture = body["pages"]
    assert text["source"] == "text" and picture["source"] == "model", [p["source"] for p in body["pages"]]
    assert DIAGRAM in picture["text"] and picture["blocks"][0]["readBy"] == "model"
    assert picture["blocks"][0]["box"] == [0.0, 0.0, 1.0, 1.0], "the description cites the whole page"
    assert len(model.calls) == 1 and model.calls[0]["parts"][0]["type"] == "image_url", model.calls
    assert again.status_code == 200 and len(model.calls) == 1, "a stored description is not asked for again"
    assert plain.json()["data"]["pages"][1]["source"] == "none", "a read that is not a knowledge read sends no picture"


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not on PATH")
async def test_a_diagram_whose_labels_ocr_reads_is_still_described(make: Make) -> None:
    """OCR reads a labelled diagram as a few words, which say nothing about how the parts connect."""
    model = Seeing()
    s = make(Models(), Floor(), pictures=PictureReading(model, Policy()))
    async with s.client as c:
        fid = await s.stored(pdf("labelled"), name="diagram.pdf", mime="application/pdf")
        body = await read_all(s, c, fid, ocr="auto")
    assert body["pages"][0]["source"] == "model" and DIAGRAM in body["pages"][0]["text"], body["pages"][0]
    assert len(model.calls) == 1


async def test_picture_reading_stops_at_its_limit_per_file_and_says_so(make: Make) -> None:
    model = Seeing()
    s = make(Models(), Floor(), pictures=PictureReading(model, Policy(), per_file=2))
    async with s.client as c:
        fid = await s.stored(pdf("picture", "picture", "picture"), name="deck.pdf", mime="application/pdf")
        body = await read_all(s, c, fid)
    sources = [p["source"] for p in body["pages"]]
    assert body["status"] == "done" and sources == ["model", "model", "none"], sources
    assert body["pages"][2]["unreadReason"] == "Not described: this file reached its limit of 2 pages read by a model."
    assert len(model.calls) == 2


@pytest.mark.parametrize(
    ("policy", "refuse", "reason"),
    [
        (False, None, "Not described: this team does not send page pictures to a model."),
        (True, "key_budget_exhausted", "Not described: today's limit for reading pictures was reached."),
        (True, "images_not_cleared", "Not described: the model is not cleared to see page pictures."),
    ],
)
async def test_a_refused_picture_leaves_its_page_unread_with_the_reason(
    make: Make, policy: bool, refuse: str | None, reason: str
) -> None:
    model = Seeing(refuse)
    s = make(Models(), Floor(), pictures=PictureReading(model, Policy(policy)))
    async with s.client as c:
        fid = await s.stored(pdf("text", "picture"), name="review.pdf", mime="application/pdf")
        body = await read_all(s, c, fid)
    assert body["status"] == "done" and body["pages"][1]["source"] == "none", body
    assert body["pages"][1]["unreadReason"] == reason
    assert len(model.calls) == (0 if not policy else 1), "a picture never leaves when the policy says no"


async def test_turning_the_policy_on_reads_a_file_read_while_it_was_off(make: Make) -> None:
    model, policy = Seeing(), Policy(on=False)
    s = make(Models(), Floor(), pictures=PictureReading(model, policy))
    async with s.client as c:
        fid = await s.stored(pdf("text", "picture"), name="review.pdf", mime="application/pdf")
        off = await read_all(s, c, fid)
        calls_off = len(model.calls)
        policy.on = True
        on = await read_all(s, c, fid)
    assert off["pages"][1]["source"] == "none" and calls_off == 0, off["pages"][1]
    assert on["pages"][1]["source"] == "model", "a reading made with pictures off is not served once they are on"


async def test_a_refusal_that_passes_is_served_then_read_again_later(make: Make) -> None:
    model = Seeing("rate_limited", times=2)
    s = make(Models(), Floor(), pictures=PictureReading(model, Policy()))
    readings = s.extractor.readings
    assert readings is not None
    now = readings.clock()
    async with s.client as c:
        fid = await s.stored(pdf("text", "picture"), name="review.pdf", mime="application/pdf")
        busy = await read_all(s, c, fid)
        soon = await c.post("/v1/documents/readings", json={"fileId": fid, **PICTURES}, headers=OPS)
        await readings.drain()
        calls_soon = len(model.calls)
        readings.clock = lambda: now + timedelta(minutes=11)
        later = await read_all(s, c, fid)
        calls_later = len(model.calls)
        readings.clock = lambda: now + timedelta(minutes=22)
        latest = await read_all(s, c, fid)
    assert busy["status"] == "done" and busy["pages"][1]["unreadReason"] == "Not described: the model was busy."
    assert soon.status_code == 200 and calls_soon == 1, "a refusal is served as read, not re-read on each ask"
    assert later["pages"][1]["source"] == "none" and calls_later == 2, "still refused: served again"
    assert busy["settings"] == {"ocr": "off", "language": "eng"}, "the answer names its settings, not its key"
    assert latest["pages"][1]["source"] == "model" and len(model.calls) == 3, latest["pages"][1]


async def test_a_page_picture_goes_at_the_files_sensitivity_and_a_refusal_says_why(make: Make) -> None:
    model = Seeing("sensitivity_not_cleared")
    s = make(Models(), Floor(), pictures=PictureReading(model, Policy()))
    async with s.client as c:
        fid = await s.stored(pdf("text", "picture"), name="merger.pdf", mime="application/pdf")
        body = await read_all(s, c, fid, sensitivity="restricted")
    assert [k["sensitivity"] for k in model.calls] == ["restricted"], model.calls
    assert body["pages"][1]["unreadReason"] == "Not described: the model is not cleared for this file's sensitivity."


async def test_a_reading_resumed_mid_file_keeps_its_limit(make: Make) -> None:
    model = Seeing(crash_at=2)
    s = make(Models(), Floor(), pictures=PictureReading(model, Policy(), per_file=2))
    async with s.client as c:
        fid = await s.stored(pdf("picture", "picture", "picture"), name="deck.pdf", mime="application/pdf")
        body = await read_all(s, c, fid)  # stops on page 2 with page 1 kept, then carries on from page 2
        for _ in range(100):
            if body["status"] == "done":
                break
            await asyncio.sleep(0.02)
            body = (await c.get(f"/v1/documents/readings/{fid}", params=PICTURES, headers=OPS)).json()["data"]
    assert [p["source"] for p in body["pages"]] == ["model", "model", "none"], [p["source"] for p in body["pages"]]
    assert body["pages"][2]["unreadReason"] == "Not described: this file reached its limit of 2 pages read by a model."
