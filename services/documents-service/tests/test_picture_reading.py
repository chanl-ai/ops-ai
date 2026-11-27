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
import sqlalchemy as sa
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.picture_reading import PictureReading
from ops_documents.store.extractions import service_outbox
from ops_service_kit.model_calls import ModelCallError

from .conftest import OPS, Make, tenant_outbox
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

    def __init__(
        self, refuse: str | None = None, *, on_calls: set[int] | None = None, crash_at: int | None = None
    ) -> None:
        # `on_calls`: refuse only those calls (1 is the first); `crash_at`: that call fails as a process dying.
        self.refuse, self.on_calls, self.crash_at = refuse, on_calls, crash_at
        self.calls: list[dict[str, Any]] = []

    async def structured(
        self, system: str, user: str, schema: dict[str, Any], *, tenant: str, step: str, **kw: Any
    ) -> Any:
        self.calls.append({"user": user, **kw})
        if self.crash_at == len(self.calls):
            raise RuntimeError("the process stopped")
        if self.refuse and (self.on_calls is None or len(self.calls) in self.on_calls):
            raise ModelCallError("refused", code=self.refuse, status=403)
        return {"text": "", "description": DIAGRAM}


class Policy:
    def __init__(self, on: bool = True) -> None:
        self.on: bool | None = on
        self.reads = 0

    async def read(self, tenant: str, team: str) -> bool | None:
        self.reads += 1
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
    pictures = PictureReading(model, policy)
    s = make(Models(), Floor(), pictures=pictures)
    async with s.client as c:
        fid = await s.stored(pdf("text", "picture"), name="review.pdf", mime="application/pdf")
        off = await read_all(s, c, fid)
        calls_off = len(model.calls)
        policy.on = True
        other = await s.stored(pdf("text", "picture"), name="deck.pdf", mime="application/pdf")
        new = await read_all(s, c, other)
        pictures.clock = lambda: 1e12  # past the time the policy is kept
        on = await read_all(s, c, fid)
    assert off["pages"][1]["source"] == "none" and calls_off == 0, off["pages"][1]
    assert new["pages"][1]["source"] == "model", "a new reading is made on the policy as it is now, not as kept"
    assert on["pages"][1]["source"] == "model", "a reading made with pictures off is not served once they are on"


def later(s: Any, minutes: float) -> None:
    """Moves the reading service's clock on, past a refused page's wait."""
    now = s.extractor.readings.clock()
    s.extractor.readings.clock = lambda: now + timedelta(minutes=minutes)


async def test_a_retry_describes_only_the_refused_page_and_serves_the_reading_meanwhile(
    make: Make, engine: AsyncEngine
) -> None:
    model = Seeing("rate_limited", on_calls={2})
    s = make(Models(), Floor(), pictures=PictureReading(model, Policy()))
    readings = s.extractor.readings
    assert readings is not None
    async with s.client as c:
        fid = await s.stored(pdf("picture", "picture"), name="deck.pdf", mime="application/pdf")
        busy = await read_all(s, c, fid)
        soon = await c.post("/v1/documents/readings", json={"fileId": fid, **PICTURES}, headers=OPS)
        await readings.drain()
        calls_soon = len(model.calls)
        later(s, 11)
        due = await c.post("/v1/documents/readings", json={"fileId": fid, **PICTURES}, headers=OPS)
        await readings.drain()
        got = (await c.get(f"/v1/documents/readings/{fid}", params=PICTURES, headers=OPS)).json()["data"]
    assert [p["source"] for p in busy["pages"]] == ["model", "none"], busy["pages"]
    assert busy["pages"][1]["unreadReason"] == "Not described: the model was busy."
    assert busy["settings"] == {"ocr": "off", "language": "eng"}, "the answer names its settings, not its key"
    assert soon.status_code == 200 and calls_soon == 2, "a refusal is served as read, not re-read on each ask"
    assert due.status_code == 200 and due.json()["data"]["pages"], "the reading is served while its page is redone"
    assert [k["user"] for k in model.calls[2:]] == ["Page 2 of the document."], "only the refused page is sent again"
    assert [p["source"] for p in got["pages"]] == ["model", "model"] and got["pages"][1]["unreadReason"] is None
    mine = service_outbox.c.tenant_id == s.tenant
    events = await tenant_outbox(
        engine,
        s.tenant,
        sa.select(service_outbox.c.name, service_outbox.c.event_key, service_outbox.c.payload).where(mine),
    )
    finished = [e for e in events if e["name"] == "reading.finished"]
    assert [e["payload"].get("redescribed") for e in finished] == [None, True], "the retry tells kb to index again"
    first, retry = (e["event_key"] for e in finished)
    assert retry == f"{first}:m2", "the retry is its own event, under the count of pages a model described"


@pytest.mark.parametrize(
    ("refuse", "minutes", "sent"),
    [
        ("rate_limited", 11, 4),
        ("upstream_failed", 11, 1),
        ("key_budget_exhausted", 11, 1),
        ("key_budget_exhausted", 1440, 6),
    ],
)
async def test_a_page_refused_every_time_stops_after_its_retries(
    make: Make, refuse: str, minutes: int, sent: int
) -> None:
    """Three retries for a refusal that passes; none for an unknown failure, which would only be paid for again. Today's
    spend limit waits for the next day and spends no retry, since no call was paid for."""
    model = Seeing(refuse)
    s = make(Models(), Floor(), pictures=PictureReading(model, Policy()))
    async with s.client as c:
        fid = await s.stored(pdf("text", "picture"), name="review.pdf", mime="application/pdf")
        body = await read_all(s, c, fid)
        for _ in range(5):
            later(s, minutes)
            body = await read_all(s, c, fid)
    assert len(model.calls) == sent, f"{len(model.calls)} pictures sent"
    assert body["pages"][1]["source"] == "none" and body["pages"][1]["unreadReason"].count("Not described") == 1


async def test_a_retry_sends_no_picture_once_the_team_turned_pictures_off(make: Make) -> None:
    model, policy = Seeing("rate_limited", on_calls={1}), Policy()
    s = make(Models(), Floor(), pictures=PictureReading(model, policy))
    readings = s.extractor.readings
    assert readings is not None
    async with s.client as c:
        fid = await s.stored(pdf("picture"), name="slide.pdf", mime="application/pdf")
        await read_all(s, c, fid)
        policy.on = False
        later(s, 11)
        await c.post("/v1/documents/readings", json={"fileId": fid, **PICTURES}, headers=OPS)
        await readings.drain()
    assert len(model.calls) == 1, "a retry asks the policy as it is now before a picture leaves"


async def test_a_queued_reading_sends_no_picture_once_the_team_turned_pictures_off(make: Make) -> None:
    model, policy = Seeing(), Policy()
    s = make(Models(), Floor(), pictures=PictureReading(model, policy))
    readings = s.extractor.readings
    assert readings is not None
    async with s.client as c:
        fid = await s.stored(pdf("picture"), name="slide.pdf", mime="application/pdf")
        asked = await c.post("/v1/documents/readings", json={"fileId": fid, **PICTURES}, headers=OPS)
        policy.on = False
        await readings.drain()
        got = (await c.get(f"/v1/documents/readings/{fid}", params=PICTURES, headers=OPS)).json()["data"]
    assert asked.status_code == 202 and model.calls == [], "the policy is asked again before a picture leaves"
    assert got["status"] == "none", "asked now, with pictures off, the file has no reading yet"


async def test_an_unread_policy_serves_the_stored_reading_and_never_reads_again(make: Make) -> None:
    model, policy = Seeing(), Policy()
    pictures = PictureReading(model, policy)
    s = make(Models(), Floor(), pictures=pictures)
    async with s.client as c:
        fid = await s.stored(pdf("text", "picture"), name="review.pdf", mime="application/pdf")
        first = await read_all(s, c, fid)
        reads_first = policy.reads
        policy.on = None
        cached = await c.post("/v1/documents/readings", json={"fileId": fid, **PICTURES}, headers=OPS)
        reads_cached = policy.reads
        pictures.clock = lambda: 1e12
        unread = await c.post("/v1/documents/readings", json={"fileId": fid, **PICTURES}, headers=OPS)
        other = await s.stored(pdf("picture"), name="slide.pdf", mime="application/pdf")
        none = await c.post("/v1/documents/readings", json={"fileId": other, **PICTURES}, headers=OPS)
    assert first["pages"][1]["source"] == "model" and cached.status_code == 200
    assert reads_cached == reads_first, "the policy is kept a while, not read on every page view"
    assert unread.status_code == 200 and unread.json()["data"]["pages"][1]["source"] == "model", unread.text
    assert none.status_code == 503 and none.json()["error"]["code"] == "policy_unread", none.text
    assert len(model.calls) == 1, "an unread policy never makes a second reading"


async def test_a_page_picture_goes_at_the_files_own_level_when_the_source_says_less(make: Make) -> None:
    """A restricted file in an internal source: the caller's level never lowers the file's."""
    model = Seeing("sensitivity_not_cleared")
    s = make(Models(), Floor(), pictures=PictureReading(model, Policy()))
    async with s.client as c:
        fid = await s.stored(pdf("text", "picture"), name="merger.pdf", mime="application/pdf")
        s.files.files[fid]["sensitivity"] = "restricted"
        body = await read_all(s, c, fid, sensitivity="internal")
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


async def test_a_reading_with_the_longest_language_list_is_kept_and_served(make: Make) -> None:
    model = Seeing()
    s = make(Models(), Floor(), pictures=PictureReading(model, Policy()))
    language = "+".join(["chi_sim_vert"] * 5)[:64].rstrip("+_")  # the request's limit, 64 characters
    asked = {"ocr": "off", "language": language, "pictureSensitivity": "confidential"}
    readings = s.extractor.readings
    assert readings is not None
    async with s.client as c:
        fid = await s.stored(pdf("text", "picture"), name="review.pdf", mime="application/pdf")
        made = await c.post("/v1/documents/readings", json={"fileId": fid, **asked}, headers=OPS)
        await readings.drain()
        got = (await c.get(f"/v1/documents/readings/{fid}", params=asked, headers=OPS)).json()["data"]
    assert made.status_code in (200, 202), made.text
    assert got["status"] == "done" and got["settings"]["language"] == language, got
    assert [p["source"] for p in got["pages"]] == ["text", "model"], got["pages"]
