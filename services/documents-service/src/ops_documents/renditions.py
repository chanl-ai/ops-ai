# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Word files and decks drawn as pages: the converter worker (deploy/images/converter) turns one into a PDF once per
content digest, kept in files-service as a `knowledge_rendition` file of the team. The PDF is what the document view
shows, what a page picture is drawn from, and, for a Word file, where each paragraph's page comes from. The worker
holds no credentials and has no network access: bytes go in, a PDF comes out, and this service does every files read
and write. With no converter configured these files are read as text only."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Protocol

import httpx
import pdfplumber

from ops_documents.files import Who
from ops_files_client import FileInfo, FilesClient, FilesRefused
from ops_ingest.reading import Block, Page, page_text
from ops_service_kit.logging import get_logger

log = get_logger("ops_documents.renditions")

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
DRAWN = (DOCX, PPTX)
PURPOSE = "knowledge_rendition"
# A conversion of a long Word file takes seconds; the worker stops its own at 90.
CONVERT_TIMEOUT_S = 120.0
# The words of a paragraph matched against a drawn page's text to find the page it is on.
MATCH_CHARS = 60
WHOLE_PAGE = [0.0, 0.0, 1.0, 1.0]
_SPACE = re.compile(r"\s+")


class ConverterError(Exception):
    """The worker could not draw the file; it is read as text only."""


class Converter(Protocol):
    async def to_pdf(self, data: bytes, *, name: str) -> bytes: ...


@dataclass
class HttpConverter:
    """The converter worker at `url`: POST /convert?name=<file name> with the bytes, answered with the PDF."""

    url: str
    timeout_s: float = CONVERT_TIMEOUT_S

    async def to_pdf(self, data: bytes, *, name: str) -> bytes:
        try:
            async with httpx.AsyncClient(base_url=self.url, timeout=self.timeout_s) as http:
                response = await http.post("/convert", params={"name": name}, content=data)
        except httpx.HTTPError as e:
            raise ConverterError(f"the converter could not be reached: {type(e).__name__}") from e
        if response.status_code != 200 or not response.content.startswith(b"%PDF"):
            raise ConverterError(f"the converter answered {response.status_code}")
        return response.content


@dataclass(frozen=True)
class Rendition:
    file_id: str
    pdf: bytes


@dataclass
class Renditions:
    converter: Converter
    files: FilesClient

    async def make(self, who: Who, file: FileInfo, data: bytes, digest: str) -> Rendition | None:
        """The file drawn as a PDF and stored for its team, or None (logged) when it cannot be drawn: the reading
        then goes on as text only."""
        stem = file.name.rsplit(".", 1)[0] or "document"
        try:
            pdf = await self.converter.to_pdf(data, name=file.name)
            stored = await self.files.write(
                who.tenant_id, who.team, pdf, name=f"{stem}.pdf", mime="application/pdf", purpose=PURPOSE,
                uploaded_by="documents-service", idempotency_key=f"rendition:{digest}",
            )  # fmt: skip
        except (ConverterError, FilesRefused, httpx.HTTPError) as e:
            log.warning("rendition_not_made", extra={"file": file.id, "error": str(e)})
            return None
        return Rendition(stored.file.id, pdf)

    async def read(self, who: Who, file_id: str) -> bytes | None:
        try:
            return await self.files.read(who.tenant_id, who.team, file_id)
        except (FilesRefused, httpx.HTTPError) as e:
            log.warning("rendition_unread", extra={"file": file_id, "error": str(e)})
            return None


def page_texts(pdf: bytes) -> list[str]:
    """Each drawn page's text, squeezed to single spaces, for finding where a paragraph landed."""
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return [_squeeze(p.extract_text() or "") for p in doc.pages]


def on_pages(mime: str, pages: list[Page], texts: list[str]) -> list[Page]:
    """The reading's pages as they are drawn. A deck's slide N is page N, so each block gets its slide's whole-page
    box. A Word file has no pages of its own: each block goes to the first drawn page, from the last block's on, whose
    text holds its opening words (a block not found stays on the page before it), with a whole-page box."""
    if mime == PPTX or not texts:
        return [_boxed(p) for p in pages]
    blocks = [b for p in pages for b in p.blocks]
    placed: dict[int, list[Block]] = {n: [] for n in range(1, len(texts) + 1)}
    at = 1
    for block in blocks:
        probe = _squeeze(block.text)[:MATCH_CHARS]
        found = next((n for n in range(at, len(texts) + 1) if probe and probe in texts[n - 1]), None)
        at = found or at
        placed[at].append(block)
    out: list[Page] = []
    for number, on_page in placed.items():
        renumbered = [
            b.model_copy(update={"id": f"p{number}.b{i}", "order": i, "box": WHOLE_PAGE}) for i, b in enumerate(on_page)
        ]
        out.append(_boxed(Page(number=number, source="text", text=page_text(renumbered), blocks=renumbered)))
    return out


def _boxed(page: Page) -> Page:
    """The page with whole-page boxes; a page with no text (a picture slide) reads as unread, so a model may describe
    it from its drawn picture."""
    if not page.text.strip():
        return page.model_copy(update={"source": "none", "blocks": []})
    return page.model_copy(update={"blocks": [b.model_copy(update={"box": WHOLE_PAGE}) for b in page.blocks]})


def _squeeze(text: str) -> str:
    return _SPACE.sub(" ", text).strip().lower()
