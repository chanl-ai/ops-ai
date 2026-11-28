"""Word files and decks drawn as pages, by failure mode: a deck's picture slide stays empty although its drawn page
shows the diagram; a Word paragraph lands on the wrong drawn page, so highlighting it shows the wrong page; the file is
drawn again on every reading; turning the converter on keeps serving the text-only reading; and a converter that is
off or fails fails the reading instead of leaving it as text. The converter is faked at its HTTP edge with a real PDF
of the same pages; the worker itself is run for real by the use case."""

from __future__ import annotations

import asyncio
import io
from typing import Any

import pytest
from docx import Document
from PIL import Image
from pptx import Presentation
from pptx.util import Inches
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas

from ops_documents.picture_reading import PictureReading
from ops_documents.renditions import DOCX, PPTX, ConverterError, Renditions
from ops_files_client import FileNotFound

from .conftest import OPS, Make
from .test_picture_reading import DIAGRAM, Policy, Seeing, read_all
from .test_picture_reading import _diagram as diagram  # pyright: ignore[reportPrivateUsage]

DECK_SLIDES = ("Claims intake review", None, "Next steps for the event queue")
NOTE_PAGES = ("Decision: we move refunds to the event queue in March.", "Open risks: the adjusters' tool lags a day.")


def deck() -> bytes:
    """Three slides; the second is only a picture."""
    prs = Presentation()
    for title in DECK_SLIDES:
        slide = prs.slides.add_slide(prs.slide_layouts[5 if title else 6])
        if title:
            heading = slide.shapes.title
            assert heading is not None
            heading.text = title
        else:
            png = io.BytesIO()
            Image.new("RGB", (90, 50), "white").save(png, "PNG")
            png.seek(0)
            slide.shapes.add_picture(png, Inches(1), Inches(1))
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def note() -> bytes:
    doc = Document()
    for text in NOTE_PAGES:
        doc.add_paragraph(text)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def drawn(*pages: str | None) -> bytes:
    """The PDF the worker would draw: one page per entry, its text, or the diagram for None."""
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    for text in pages:
        if text is None:
            c.drawImage(diagram(), 72, 300, width=450, height=250)  # pyright: ignore[reportUnknownMemberType]
        else:
            c.drawString(72, 700, text)
        c.showPage()
    c.save()
    return buf.getvalue()


class Converter:
    """The worker's HTTP edge: answers each file with the PDF of its pages, or fails."""

    def __init__(self, fails: bool = False) -> None:
        self.fails, self.calls = fails, 0

    async def to_pdf(self, data: bytes, *, name: str) -> bytes:
        self.calls += 1
        if self.fails:
            raise ConverterError("the converter answered 504")
        return drawn(*DECK_SLIDES) if name.endswith(".pptx") else drawn(*NOTE_PAGES)


async def test_a_deck_picture_slide_is_described_from_its_drawn_page_and_drawn_once(make: Make) -> None:
    model, converter = Seeing(), Converter()
    s = make(pictures=PictureReading(model, Policy()), converter=converter)
    fid = await s.stored(deck(), name="review.pptx", mime=PPTX)
    async with s.client as c:
        first = await read_all(s, c, fid)
        again = await read_all(s, c, fid, sensitivity="confidential")
        image = await c.get(f"/v1/documents/readings/{fid}/pages/2/image", headers=OPS)
    slide = first["pages"][1]
    assert slide["source"] == "model" and slide["blocks"][0]["readBy"] == "model", slide
    assert DIAGRAM in slide["text"] and len(model.calls) == 2, "the picture slide is sent once per reading"
    assert all(b["box"] == [0.0, 0.0, 1.0, 1.0] for p in first["pages"] for b in p["blocks"]), "whole-slide boxes"
    rendition = first["renditionId"]
    assert rendition and again["renditionId"] == rendition and converter.calls == 1, "drawn once per content"
    assert s.files.files[rendition]["purpose"] == "knowledge_rendition"
    assert image.status_code == 200 and image.headers["content-type"] == "image/png", image.text


async def test_a_word_paragraph_lands_on_the_page_it_is_drawn_on(make: Make) -> None:
    s = make(converter=Converter())
    fid = await s.stored(note(), name="decision.docx", mime=DOCX)
    async with s.client as c:
        got = await read_all(s, c, fid)
    on = [[b["text"] for b in p["blocks"]] for p in got["pages"]]
    assert on == [[NOTE_PAGES[0]], [NOTE_PAGES[1]]], on
    assert got["facts"]["paged"] is True and got["facts"]["pageCount"] == 2


@pytest.mark.parametrize("converter", [None, Converter(fails=True)], ids=["off", "failing"])
async def test_without_a_drawing_the_file_still_shows_its_text(make: Make, converter: Any) -> None:
    s = make(converter=converter)
    fid = await s.stored(deck(), name="review.pptx", mime=PPTX)
    async with s.client as c:
        got = await read_all(s, c, fid)
    assert got["status"] == "done" and got["renditionId"] is None, got
    assert got["pages"][0]["text"].startswith(DECK_SLIDES[0]), got["pages"]
    slide = got["pages"][1]
    assert slide["source"] == "none" and "not described" in (slide["unreadReason"] or ""), slide


async def test_turning_the_converter_on_draws_a_file_read_without_it(make: Make) -> None:
    s = make()
    fid = await s.stored(note(), name="decision.docx", mime=DOCX)
    readings = s.extractor.readings
    assert readings is not None
    async with s.client as c:
        before = await read_all(s, c, fid)
        s.files.clean_on_write = ("knowledge_rendition",)
        writer = s.files.client(service="documents", scopes=["files:create", "files:view"])
        readings.renditions = Renditions(Converter(), writer, scan_wait_s=0.2, scan_poll_s=0.02)
        after = await read_all(s, c, fid)
    assert before["renditionId"] is None and after["renditionId"], after


async def test_a_drawing_waiting_on_its_scan_keeps_the_reading_waiting_and_is_not_drawn_again(make: Make) -> None:
    converter = Converter()
    s = make(converter=converter, rendition_scan="pending")
    readings = s.extractor.readings
    assert readings is not None and readings.renditions is not None
    readings.renditions.scan_wait_s = 5.0
    fid = await s.stored(deck(), name="review.pptx", mime=PPTX)
    asked = {"ocr": "off", "pictureSensitivity": "internal"}
    async with s.client as c:
        await c.post("/v1/documents/readings", json={"fileId": fid, **asked}, headers=OPS)
        drawn: list[str] = []
        for _ in range(500):  # at most 5 s for the reading to draw the deck
            if drawn := [k for k, f in s.files.files.items() if f["purpose"] == "knowledge_rendition"]:
                break
            await asyncio.sleep(0.01)
        waiting = (await c.get(f"/v1/documents/readings/{fid}", params=asked, headers=OPS)).json()["data"]
        await s.files.client(service="scanner", scopes=["files:decide"]).report_scan(
            s.tenant, drawn[0], status="clean", engine="clamav"
        )
        await readings.drain()
        done = (await c.get(f"/v1/documents/readings/{fid}", params=asked, headers=OPS)).json()["data"]
    assert waiting["status"] in ("queued", "reading"), waiting
    assert done["status"] == "done" and done["renditionId"] == drawn[0], done
    assert converter.calls == 1 and len(drawn) == 1, "drawn once while its scan was waited on"


async def test_the_same_file_in_two_teams_gets_a_drawing_each_that_the_other_cannot_read(make: Make) -> None:
    s = make(converter=Converter())
    readings = s.extractor.readings
    assert readings is not None
    ours = await s.stored(deck(), name="review.pptx", mime=PPTX)
    theirs = await s.stored(deck(), name="review.pptx", mime=PPTX, team="team_cards")
    cards = {"X-Team-Id": "team_cards"}
    asked = {"ocr": "off", "pictureSensitivity": "internal"}
    async with s.client as c:
        a = await read_all(s, c, ours)
        await c.post("/v1/documents/readings", json={"fileId": theirs, **asked}, headers=cards)
        await readings.drain()
        b = (await c.get(f"/v1/documents/readings/{theirs}", params=asked, headers=cards)).json()["data"]
    assert a["renditionId"] and b["renditionId"] and a["renditionId"] != b["renditionId"], (a, b)
    assert s.files.files[b["renditionId"]]["team"] == "team_cards"
    with pytest.raises(FileNotFound):
        await s.files.client(service="documents", scopes=["files:view"]).get(s.tenant, "team_cards", a["renditionId"])
