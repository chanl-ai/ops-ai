"""Picture reading, by failure mode: a page with no text stays empty although a model could describe it; a page with
text is sent to the model anyway; a described page is sent again on the next ask; a long file of pictures runs past
its limit with nothing saying where it stopped; a picture leaves the service although the team's policy says no; and
a refused model call fails the whole reading instead of leaving that one page unread with the reason."""

from __future__ import annotations

import io
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


def pdf(*pages: str) -> bytes:
    """One page per entry: "text" draws a sentence, "picture" only the diagram."""
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    for kind in pages:
        if kind == "text":
            c.drawString(72, 700, "Claims intake review: the event queue went live in three regions.")
        else:
            c.drawImage(_diagram(), 72, 300, width=450, height=250)  # pyright: ignore[reportUnknownMemberType]
        c.showPage()
    c.save()
    return buf.getvalue()


class Seeing:
    """The model edge: answers each page picture with a description, or refuses with a models-service code."""

    def __init__(self, refuse: str | None = None) -> None:
        self.refuse = refuse
        self.calls: list[dict[str, Any]] = []

    async def structured(
        self, system: str, user: str, schema: dict[str, Any], *, tenant: str, step: str, **kw: Any
    ) -> Any:
        self.calls.append(kw)
        if self.refuse:
            raise ModelCallError("refused", code=self.refuse, status=403)
        return {"text": "", "description": DIAGRAM}


class Policy:
    def __init__(self, on: bool = True) -> None:
        self.on = on

    async def allowed(self, tenant: str, team: str) -> bool:
        return self.on


async def read_all(s: Any, c: httpx.AsyncClient, fid: str) -> dict[str, Any]:
    await c.post("/v1/documents/readings", json={"fileId": fid, "ocr": "off"}, headers=OPS)
    await s.extractor.readings.drain()
    got = await c.get(f"/v1/documents/readings/{fid}", params={"ocr": "off"}, headers=OPS)
    return got.json()["data"]


async def test_a_picture_page_is_described_once_and_a_text_page_is_not_sent(make: Make) -> None:
    model = Seeing()
    s = make(Models(), Floor(), pictures=PictureReading(model, Policy()))
    async with s.client as c:
        fid = await s.stored(pdf("text", "picture"), name="review.pdf", mime="application/pdf")
        body = await read_all(s, c, fid)
        again = await c.post("/v1/documents/readings", json={"fileId": fid, "ocr": "off"}, headers=OPS)
    assert body["status"] == "done", body
    text, picture = body["pages"]
    assert text["source"] == "text" and picture["source"] == "model", [p["source"] for p in body["pages"]]
    assert DIAGRAM in picture["text"] and picture["blocks"][0]["readBy"] == "model"
    assert picture["blocks"][0]["box"] == [0.0, 0.0, 1.0, 1.0], "the description cites the whole page"
    assert len(model.calls) == 1 and model.calls[0]["parts"][0]["type"] == "image_url", model.calls
    assert again.status_code == 200 and len(model.calls) == 1, "a stored description is not asked for again"


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
