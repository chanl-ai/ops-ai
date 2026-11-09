# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""A file's layout: pages, blocks and table cells with ids, boxes as fractions of the page from the top left,
and reading order, and words with a confidence (1.0 on a text layer, Tesseract's on OCR). It is a view of the file's
reading (`ops_ingest.reading`), so a file read once serves extraction, highlights, templates and classify, and
`page_text` renders the text an extraction reads.

Each line of a paragraph is a `line` block of its own, so a highlight or a template can name the line a value sits on;
a format without page boxes (DOCX, HTML, spreadsheets, text) keeps whole paragraphs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from ops_extract.checks import fold
from ops_extract.pages import Pages
from ops_ingest.reading import READER_VERSION, Reading, ReadingSettings, WordOcr, read
from ops_ingest.reading.pdf import OCR_RESOLUTION

# Part of every stored layout's key: the reader's own version, so a change to how files are read reads them again.
ENGINE = READER_VERSION

Layout = dict[str, Any]

__all__ = ["ENGINE", "OCR_RESOLUTION", "Layout", "build_layout", "layout_of", "page_text"]


def layout_of(reading: Reading) -> Layout:
    """The reading as a layout: one block per title, heading, table and paragraph line, numbered in reading order."""
    pages: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []
    for page in reading.pages:
        n = page.number
        pages.append({"number": n, "width": page.width, "height": page.height, "source": page.source})
        found: list[tuple[str, str, list[float] | None, list[dict[str, Any]] | None]] = []
        for b in page.blocks:
            if b.kind == "table":
                cells = [
                    {
                        "id": c.id,
                        "row": c.row,
                        "col": c.col,
                        "rowSpan": c.row_span,
                        "colSpan": c.col_span,
                        "text": c.text,
                        "box": c.box,
                    }
                    for c in b.cells
                ]
                found.append(("table", b.text, b.box, cells))
            elif b.kind == "paragraph" and b.lines:
                found.extend(("line", line.text, line.box, None) for line in b.lines)
            else:
                found.append((b.kind, b.text, b.box, None))
        for i, (kind, text, box, cells) in enumerate(found):
            block: dict[str, Any] = {"id": f"p{n}.b{i}", "page": n, "kind": kind, "text": text, "box": box}
            block["order"] = len(blocks)
            if cells is not None:
                block["cells"] = cells
            blocks.append(block)
        words.extend({"page": n, "text": w.text, "box": w.box, "conf": w.confidence} for w in page.words)
    return {"engine": ENGINE, "pages": pages, "blocks": blocks, "words": words}


def build_layout(
    data: bytes, *, filename: str, mime: str | None = None, ocr: bool = False, engine: WordOcr | None = None
) -> Layout:
    """The file read and shown as a layout; `ocr` reads scans and the picture parts of mixed pages (OCR `auto`), and
    without it a page with no text layer is listed with source "none" and no blocks."""
    settings = ReadingSettings(ocr="auto" if ocr else "off")
    return layout_of(read(data, filename=filename, mime_type=mime, settings=settings, ocr_engine=engine))


def _lines(block: dict[str, Any]) -> Iterable[str]:
    if block["kind"] == "table":
        cells = cast(list[dict[str, Any]], block.get("cells") or [])
        for row in sorted({int(c["row"]) for c in cells}):
            texts = [
                str(c["text"]) for c in sorted(cells, key=lambda c: int(c["col"])) if c["row"] == row and c["text"]
            ]
            if len(texts) == 2:
                # A label and its value on lines of their own: joined as "label | value" the model copied the whole
                # row into the value (24 of the baseline's 35 misses).
                yield from texts
            elif texts:
                # A wider row is a record (a spreadsheet's or a CSV's), kept on one line so its values stay together.
                yield " | ".join(texts)
    else:
        yield block["text"]


def page_text(layout: Layout) -> Pages:
    """The text an extraction reads and quotes are checked against, one string per page in reading order, with the
    OCR'd pages and each OCR'd page's word confidences (folded word to its highest confidence on that page)."""
    texts: dict[int, list[str]] = {}
    for block in cast(list[dict[str, Any]], layout["blocks"]):
        texts.setdefault(int(block["page"]), []).extend(_lines(block))
    joined = {n: "\n".join(t) for n, t in texts.items() if any(s.strip() for s in t)}
    # A mixed page's text-layer words carry confidence 1.0, so only its OCR'd words count for less.
    read_by_ocr = ("ocr", "mixed")
    ocr = {int(p["number"]) for p in layout["pages"] if p["source"] in read_by_ocr and int(p["number"]) in joined}
    confidence: dict[int, dict[str, float]] = {}
    for word in cast(list[dict[str, Any]], layout["words"]):
        page = int(word["page"])
        if page in ocr:
            key = fold(str(word["text"]))
            on_page = confidence.setdefault(page, {})
            on_page[key] = max(on_page.get(key, 0.0), float(word["conf"]))
    return Pages(joined, ocr, max(len(layout["pages"]), 1), confidence, layout)
