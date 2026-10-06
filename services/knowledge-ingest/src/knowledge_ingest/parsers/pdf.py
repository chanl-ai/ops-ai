# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""PDF through pdfplumber: text, tables with their header row, headings by font size, OCR fallback.

Table regions are removed from the page before its text is read, so a table's cells are not
indexed twice (once as prose, once as rows). A page with no characters is a scanned page: with
`parsing.ocr` it is rendered and read by the OCR engine; without it the page is listed in
`pages_without_text` and a warning names it, so an empty item is never mistaken for a short one.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, cast

import pdfplumber

from knowledge_ingest.models import ParsedDocument, ParsingSettings, SourceMetadata, Table
from knowledge_ingest.parsers.builder import DocumentBuilder
from knowledge_ingest.parsers.ocr import OcrEngine, TesseractEngine

MAX_PAGES = 2_000
OCR_RESOLUTION = 200
_HEADING_RATIO = 1.15
_HEADING_MAX_CHARS = 150
_CAPTION = re.compile(r"^table\b", re.IGNORECASE)


@dataclass
class _Line:
    page: int
    top: float
    bottom: float
    text: str
    size: float


@dataclass
class _TableAt:
    page: int
    top: float
    table: Table


def _inside(obj: dict[str, Any], boxes: list[tuple[float, float, float, float]]) -> bool:
    cx = (float(obj["x0"]) + float(obj["x1"])) / 2
    cy = (float(obj["top"]) + float(obj["bottom"])) / 2
    return any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boxes)


def _table_from_rows(raw: list[list[str | None]], page: int) -> Table | None:
    rows = [[" ".join((c or "").split()) for c in row] for row in raw]
    rows = [r for r in rows if any(r)]
    if not rows:
        return None
    return Table(headers=rows[0], rows=rows[1:], page=page)


def parse_pdf(
    data: bytes,
    *,
    filename: str,
    parsing: ParsingSettings | None = None,
    fields: dict[str, str] | None = None,
    ocr_engine: OcrEngine | None = None,
) -> ParsedDocument:
    parsing = parsing or ParsingSettings()
    builder = DocumentBuilder()
    lines: list[_Line] = []
    tables: list[_TableAt] = []
    ocr_text: dict[int, str] = {}

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        meta = cast(dict[str, Any], pdf.metadata or {})  # pyright: ignore[reportUnknownMemberType]
        page_count = len(pdf.pages)
        if page_count > MAX_PAGES:
            builder.warnings.append(f"The PDF has {page_count} pages; only the first {MAX_PAGES} were read.")
        for number, page in enumerate(pdf.pages[:MAX_PAGES], start=1):
            if not page.chars:
                if parsing.ocr:
                    engine = ocr_engine or TesseractEngine()
                    image = page.to_image(resolution=OCR_RESOLUTION).original
                    ocr_text[number] = engine.image_to_text(image)
                    builder.ocr_pages.append(number)
                else:
                    builder.pages_without_text.append(number)
                    builder.warnings.append(f"Page {number} has no text layer and OCR is off, so it was not read.")
                continue

            boxes: list[tuple[float, float, float, float]] = []
            if parsing.tables:
                for found in page.find_tables():
                    table = _table_from_rows(found.extract(), number)
                    if table is None:
                        continue
                    x0, top, x1, bottom = (float(v) for v in found.bbox)
                    boxes.append((x0, top, x1, bottom))
                    tables.append(_TableAt(page=number, top=top, table=table))
            text_page = page.filter(lambda obj, b=boxes: not _inside(obj, b)) if boxes else page
            for raw in text_page.extract_text_lines(return_chars=True):
                chars = cast(list[dict[str, Any]], raw.get("chars", []))
                sizes = [float(c["size"]) for c in chars if str(c.get("text", "")).strip()]
                text = " ".join(str(raw["text"]).split())
                if text and sizes:
                    lines.append(_Line(number, float(raw["top"]), float(raw["bottom"]), text, sum(sizes) / len(sizes)))

    _assemble(builder, lines, tables, ocr_text, keep_tables=parsing.tables)

    title = str(meta.get("Title") or "").strip() or None
    source = SourceMetadata(
        filename=filename,
        mime_type="application/pdf",
        size_bytes=len(data),
        title=title,
        author=str(meta.get("Author") or "").strip() or None,
        created=str(meta.get("CreationDate") or "") or None,
        modified=str(meta.get("ModDate") or "") or None,
        page_count=page_count,
        fields=fields or {},
    )
    return builder.build(title=title, source=source)


def _assemble(
    builder: DocumentBuilder,
    lines: list[_Line],
    tables: list[_TableAt],
    ocr_text: dict[int, str],
    *,
    keep_tables: bool,
) -> None:
    size_counts = Counter(round(line.size, 1) for line in lines for _ in line.text)
    body = size_counts.most_common(1)[0][0] if size_counts else 0.0
    heading_sizes = sorted(
        {round(ln.size, 1) for ln in lines if body and ln.size >= body * _HEADING_RATIO}, reverse=True
    )
    level_of = {size: i + 1 for i, size in enumerate(heading_sizes)}

    events: list[tuple[int, float, _Line | _TableAt]] = [(ln.page, ln.top, ln) for ln in lines]
    events.extend((t.page, t.top, t) for t in tables)
    events.sort(key=lambda e: (e[0], e[1]))

    pages = sorted({e[0] for e in events} | set(ocr_text))
    paragraph: list[str] = []
    paragraph_page: int | None = None
    previous: _Line | None = None

    def flush() -> None:
        nonlocal paragraph_page
        if paragraph:
            builder.paragraph(" ".join(paragraph), paragraph_page)
            paragraph.clear()
        paragraph_page = None

    for page in pages:
        if page in ocr_text:
            flush()
            for block in re.split(r"\n\s*\n", ocr_text[page]):
                builder.paragraph(" ".join(block.split()), page)
            previous = None
            continue
        for _, _, item in (e for e in events if e[0] == page):
            if isinstance(item, _TableAt):
                caption = None
                if paragraph and _CAPTION.match(paragraph[-1]):
                    caption = paragraph.pop()
                flush()
                t = item.table
                builder.table(t.headers, t.rows, page=t.page, caption=caption, keep_as_table=keep_tables)
                previous = None
                continue
            size = round(item.size, 1)
            if size in level_of and len(item.text) <= _HEADING_MAX_CHARS:
                flush()
                builder.heading(item.text, level_of[size], page)
                previous = None
                continue
            height = max(item.bottom - item.top, 1.0)
            if previous is not None and (previous.page != item.page or item.top - previous.bottom > 0.8 * height):
                flush()
            if paragraph_page is None:
                paragraph_page = item.page
            paragraph.append(item.text)
            previous = item
        flush()
        previous = None
