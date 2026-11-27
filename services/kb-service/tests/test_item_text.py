"""An item's text beside its original, by failure mode: the text loses its sections, so a person cannot read it
section by section; a paragraph carries no place on the page, so selecting it highlights nothing; a page a model
described is shown as the author's words, or is not citable at its own page; a page left unread says nothing about
why; and a file without pages (Markdown, Word) claims places on a page it does not have."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import httpx
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_contracts import readings as readings_contract
from ops_identity.fastapi import DEV_TEAM
from ops_ingest.reading import READER_VERSION
from ops_kb.files import KnowledgeFiles

from .conftest import kb_client
from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_readings import base_with, documents
from .test_retrieval import ask

DIAGRAM = "Three boxes, Mobile app, Intake service and Event queue, joined left to right by arrows."


def review_pdf() -> bytes:
    """Page 1: a heading and a two-line paragraph. Page 2: nothing in its text layer (a picture). Page 3: blank, left
    unread by the reader."""
    out = io.BytesIO()
    c = Canvas(out, pagesize=LETTER)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, 720, "Claims intake review")
    c.setFont("Helvetica", 11)
    c.drawString(72, 680, "The event queue went live in three regions in October and carries")
    c.drawString(72, 666, "every claim photo to the adjusters within five minutes of upload.")
    c.showPage()
    c.showPage()
    c.showPage()
    c.save()
    return out.getvalue()


class _NoWords:
    """OCR that finds no words, so the diagram page is left for the model without Tesseract installed."""

    def image_to_words(self, image: object) -> list[Any]:
        del image
        return []


async def test_item_text_has_sections_line_boxes_and_the_model_page_marked(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    intake = KnowledgeFiles(tmp_path)
    readings = LocalReadings(intake, engine=_NoWords())
    readings.described = {2: DIAGRAM}
    async with kb_client(engine, tenant, files=intake, readings=readings) as client:
        src, kb = await base_with(client, ("review.pdf", review_pdf()))
        await client.post(f"/v1/sources/{src['id']}/sync")
        item = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"][0]
        text: dict[str, Any] = data(await client.get(f"/v1/items/{item['id']}/text"))
        second: dict[str, Any] = data(await client.get(f"/v1/items/{item['id']}/text", params={"page": 2}))
        past: dict[str, Any] = data(await client.get(f"/v1/items/{item['id']}/text", params={"page": 99}))
        answer = await ask(client, kb["id"], "How do the mobile app and the event queue connect?")
    assert text["status"] == "done" and text["paged"] is True, text
    paths = [s["headingPath"] for s in text["sections"]]
    assert paths[0] == ["Claims intake review"], paths
    paragraph = text["sections"][0]["blocks"][0]
    assert paragraph["kind"] == "paragraph" and "five minutes" in paragraph["text"], paragraph
    assert len(paragraph["boxes"]) == 2 and {b["page"] for b in paragraph["boxes"]} == {1}, "one box per line"
    assert text["page"] == 1 and all(b["page"] == 1 for s in text["sections"] for b in s["blocks"]), "one page a time"
    described = [b for s in second["sections"] for b in s["blocks"] if b["readBy"] == "model"]
    assert len(described) == 1 and described[0]["page"] == 2 and described[0]["boxes"][0]["w"] == 1.0, described
    assert second["sections"][0]["headingPath"] == ["Claims intake review"], "headings carry over from earlier pages"
    assert second["sections"][0]["page"] == 2, "a section running on is shown at the page asked for"
    assert past["page"] == 3 and past["sections"] == [], "a page past the last is the last"
    pages = {p["number"]: p for p in text["pages"]}
    assert pages[2]["readBy"] == "model" and pages[3]["unreadReason"], pages
    assert text["notes"] == [f"Page 3 was not read. {pages[3]['unreadReason']}"], text["notes"]
    assert any(c["page"] == 2 for c in answer["citations"]), answer["citations"]


async def test_text_of_a_file_without_pages_has_sections_and_no_boxes(client: httpx.AsyncClient) -> None:
    body = {"type": "text", "name": "Notes", "collection": "Notes", "owner": "james@harborpine.example"}
    src = data(await client.post("/v1/sources", json=body), 201)
    put = {
        "name": "refunds.md",
        "text": "# Refunds\n\nRefunds post within two days.\n\n# Disputes\n\nA dispute pauses it.",
    }
    item = data(await client.post(f"/v1/sources/{src['id']}/items", json=put))
    text = data(await client.get(f"/v1/items/{item['item']['id']}/text"))
    assert text["status"] == "done" and text["paged"] is False, text
    assert [s["headingPath"] for s in text["sections"]] == [["Refunds"], ["Disputes"]], text["sections"]
    assert all(b["page"] is None and b["boxes"] == [] for s in text["sections"] for b in s["blocks"])


async def test_a_page_described_on_a_retry_reaches_search(engine: AsyncEngine, tenant: str, tmp_path: Path) -> None:
    intake = KnowledgeFiles(tmp_path)
    readings = LocalReadings(intake, engine=_NoWords())
    async with kb_client(engine, tenant, files=intake, readings=readings) as client:
        src, kb = await base_with(client, ("review.pdf", review_pdf()))
        await client.post(f"/v1/sources/{src['id']}/sync")
        item = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"][0]
        # documents-service describes page 2 on a retry and says so again, as its own event for that reading.
        readings.described, readings.kept = {2: DIAGRAM}, {}

        async def finished(key: str) -> int:
            said = {"fileId": item["fileId"], "readerVersion": READER_VERSION, "settingsKey": key, "redescribed": True}
            name = readings_contract.FINISHED
            at = readings_contract.event_key(
                name, digest=item["digest"], reader_version=READER_VERSION, settings_key=key, file_id=item["fileId"],
                described=1,
            )  # fmt: skip
            event = {"name": name, "key": at, "teamId": DEV_TEAM, "payload": said}
            sent = await client.post("/v1/events", json=event, headers=documents(tenant))
            return int(sent.json()["data"]["items"])

        mine = f"auto:eng:p-{src['sensitivity']}"
        settled = [await finished(f"auto:fra:p-{src['sensitivity']}"), await finished(mine), await finished(mine)]
        answer = await ask(client, kb["id"], "How do the mobile app and the event queue connect?")
    # Another reading of the file settles nothing; the item's own once; the same event again nothing more.
    assert item["status"] == "indexed" and settled == [0, 1, 0], settled
    assert any(c.get("page") == 2 for c in answer["citations"]), answer
