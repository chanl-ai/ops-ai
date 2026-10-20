# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""A file's layout (c-247): pages, blocks and table cells with ids, boxes as fractions of the page from the top left,
and reading order, and words with a confidence (1.0 on a text layer, Tesseract's on OCR). One layout is read once per
file and shared by extraction, highlights, templates and classify; `page_text` renders the text an extraction reads.

Boxes are fractions of the page so a zone holds whatever the scan resolution. A PDF's text layer and tables come from
pdfplumber, a page without one from Tesseract's word data; other formats get blocks without boxes."""

from __future__ import annotations

import io
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol, cast

import pdfplumber

from ops_extract.checks import fold
from ops_extract.pages import Pages
from ops_ingest import ParsedDocument
from ops_ingest.models import ParsingSettings, Table
from ops_ingest.parsers import parse
from ops_ingest.parsers.ocr import OcrWord, TesseractEngine

# Part of every cached layout's key: a change to how layouts are built bumps it, so no stale layout is served.
ENGINE = "layout-3"
OCR_RESOLUTION = 200
MAX_PAGES = 200
# A line this much larger than the document's body text is a heading; this much and on page 1, the title.
HEADING_RATIO = 1.15
TITLE_RATIO = 1.5
HEADING_MAX_CHARS = 120

Layout = dict[str, Any]
Box = list[float]


class WordOcr(Protocol):
    def image_to_words(self, image: object) -> list[OcrWord]: ...


@dataclass
class _Block:
    page: int
    kind: str
    text: str
    box: Box | None
    cells: list[dict[str, Any]] | None = None


def _frac(box: tuple[float, float, float, float], width: float, height: float) -> Box:
    x0, top, x1, bottom = box
    return [round(x0 / width, 4), round(top / height, 4), round(x1 / width, 4), round(bottom / height, 4)]


def _inside(box: tuple[float, float, float, float], tables: list[tuple[float, float, float, float]]) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(x0 <= cx <= x1 and t <= cy <= b for x0, t, x1, b in tables)


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _text_page(page: Any, number: int, body: float, blocks: list[_Block], words: list[dict[str, Any]]) -> None:
    width, height = float(page.width), float(page.height)
    tables: list[tuple[float, float, float, float]] = []
    for t_index, found in enumerate(page.find_tables()):
        x0, top, x1, bottom = (float(v) for v in found.bbox)
        cells: list[dict[str, Any]] = []
        for r_index, row in enumerate(found.rows):
            raw = cast(list[Any], row.cells)
            for c_index, cell in enumerate(raw):
                if cell is None:
                    continue  # covered by a merged cell to its left
                span = 1
                while c_index + span < len(raw) and raw[c_index + span] is None:
                    span += 1
                cx0, ctop, cx1, cbottom = (float(v) for v in cell)
                text = _clean(page.crop((cx0, ctop, cx1, cbottom)).extract_text())
                cells.append(
                    {
                        "id": f"p{number}.t{t_index}.r{r_index}.c{c_index}",
                        "row": r_index,
                        "col": c_index,
                        "rowSpan": 1,
                        "colSpan": span,
                        "text": text,
                        "box": _frac((cx0, ctop, cx1, cbottom), width, height),
                    }
                )
        if any(c["text"] for c in cells):
            tables.append((x0, top, x1, bottom))
            text = "\n".join(c["text"] for c in cells if c["text"])
            blocks.append(_Block(number, "table", text, _frac((x0, top, x1, bottom), width, height), cells))
    found = [cast(dict[str, Any], w) for w in page.extract_words(extra_attrs=["size", "fontname"])]
    for word in found:
        box = (float(word["x0"]), float(word["top"]), float(word["x1"]), float(word["bottom"]))
        words.append({"page": number, "text": str(word["text"]), "box": _frac(box, width, height), "conf": 1.0})
    outside = [
        w for w in found if not _inside((float(w["x0"]), float(w["top"]), float(w["x1"]), float(w["bottom"])), tables)
    ]
    for segment in _segments(outside):
        box = (
            min(float(w["x0"]) for w in segment),
            min(float(w["top"]) for w in segment),
            max(float(w["x1"]) for w in segment),
            max(float(w["bottom"]) for w in segment),
        )
        text = " ".join(str(w["text"]) for w in segment)
        size = statistics.fmean(float(w["size"]) for w in segment)
        bold = all("bold" in str(w.get("fontname", "")).lower() for w in segment)
        kind = "line"
        if len(text) <= HEADING_MAX_CHARS:
            if number == 1 and size >= body * TITLE_RATIO:
                kind = "title"
            elif size >= body * HEADING_RATIO or bold:
                kind = "heading"
        blocks.append(_Block(number, kind, text, _frac(box, width, height)))


def _segments(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Words into lines (tops within 2 points), each line split where the gap to the next word is wider than three
    times the font size, so two columns side by side (a court caption's parties and its index number) stay apart."""
    rows: list[list[dict[str, Any]]] = []
    for w in sorted(words, key=lambda w: (float(w["top"]), float(w["x0"]))):
        if rows and abs(float(rows[-1][0]["top"]) - float(w["top"])) <= 2:
            rows[-1].append(w)
        else:
            rows.append([w])
    out: list[list[dict[str, Any]]] = []
    for row in rows:
        row.sort(key=lambda w: float(w["x0"]))
        current = [row[0]]
        for w in row[1:]:
            if float(w["x0"]) - float(current[-1]["x1"]) > 3 * float(w["size"]):
                out.append(current)
                current = [w]
            else:
                current.append(w)
        out.append(current)
    return out


def _ocr_page(page: Any, number: int, engine: WordOcr, blocks: list[_Block], words: list[dict[str, Any]]) -> None:
    image = page.to_image(resolution=OCR_RESOLUTION).original
    iw, ih = float(image.width), float(image.height)
    lines: dict[tuple[int, int, int], list[OcrWord]] = {}
    for w in engine.image_to_words(image):
        left, top, wd, ht = w.box
        words.append(
            {
                "page": number,
                "text": w.text,
                "box": _frac((left, top, left + wd, top + ht), iw, ih),
                "conf": w.confidence,
            }
        )
        lines.setdefault(w.line, []).append(w)
    for members in lines.values():
        x0 = min(w.box[0] for w in members)
        top = min(w.box[1] for w in members)
        x1 = max(w.box[0] + w.box[2] for w in members)
        bottom = max(w.box[1] + w.box[3] for w in members)
        blocks.append(_Block(number, "line", " ".join(w.text for w in members), _frac((x0, top, x1, bottom), iw, ih)))


def _body_size(pdf: Any) -> float:
    sizes = [float(c["size"]) for p in pdf.pages[:MAX_PAGES] for c in p.chars if str(c.get("text", "")).strip()]
    return statistics.median(sizes) if sizes else 10.0


def _ordered(blocks: list[_Block]) -> list[dict[str, Any]]:
    """Blocks in reading order, top to bottom then left to right on each page, with their ids; a cell keeps its own."""
    out: list[dict[str, Any]] = []
    for page in sorted({b.page for b in blocks}):
        on_page = [b for b in blocks if b.page == page]
        on_page.sort(key=lambda b: (b.box[1], b.box[0]) if b.box else (0.0, 0.0))
        for i, b in enumerate(on_page):
            block: dict[str, Any] = {"id": f"p{page}.b{i}", "page": page, "kind": b.kind, "text": b.text, "box": b.box}
            block["order"] = len(out)
            if b.cells is not None:
                block["cells"] = b.cells
            out.append(block)
    return out


def _pdf_layout(data: bytes, *, ocr: bool, engine: WordOcr | None) -> Layout:
    blocks: list[_Block] = []
    words: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        body = _body_size(pdf)
        for number, page in enumerate(pdf.pages[:MAX_PAGES], start=1):
            source = "text"
            if page.chars:
                _text_page(page, number, body, blocks, words)
            elif ocr:
                source = "ocr"
                _ocr_page(page, number, engine or TesseractEngine(), blocks, words)
            else:
                source = "none"
            pages.append({"number": number, "width": float(page.width), "height": float(page.height), "source": source})
    return {"engine": ENGINE, "pages": pages, "blocks": _ordered(blocks), "words": words}


def _parsed_layout(doc: ParsedDocument) -> Layout:
    """DOCX, HTML, text and spreadsheets: the parser's sections as blocks, without boxes."""
    blocks: list[_Block] = []
    for section in doc.sections:
        page = section.page or 1
        if section.heading_path and section.heading_path[-1].strip():
            blocks.append(_Block(page, "heading", section.heading_path[-1], None))
        for b in section.blocks:
            if isinstance(b, Table):
                rows = [b.headers, *b.rows]
                cells: list[dict[str, Any]] = [
                    {"id": "", "row": r, "col": c, "rowSpan": 1, "colSpan": 1, "text": _clean(t), "box": None}
                    for r, row in enumerate(rows)
                    for c, t in enumerate(row)
                ]
                text = "\n".join(str(c["text"]) for c in cells if c["text"])
                blocks.append(_Block(b.page or page, "table", text, None, cells))
            elif b.text.strip():
                blocks.append(_Block(b.page or page, "paragraph", b.text, None))
    ordered = _ordered(blocks)
    for block in ordered:
        for cell in cast(list[dict[str, Any]], block.get("cells") or []):
            cell["id"] = f"{block['id']}.r{cell['row']}.c{cell['col']}"
    count = max([b.page for b in blocks] or [doc.source.page_count or 1])
    pages = [{"number": n, "width": None, "height": None, "source": "text"} for n in range(1, count + 1)]
    return {"engine": ENGINE, "pages": pages, "blocks": ordered, "words": []}


def build_layout(
    data: bytes, *, filename: str, mime: str | None = None, ocr: bool = False, engine: WordOcr | None = None
) -> Layout:
    """The file's layout; a page with no text layer is OCR'd only when `ocr` is asked, else it is listed with source
    "none" and no blocks, so an unreadable scan is told apart from a short page."""
    if mime == "application/pdf" or filename.lower().endswith(".pdf"):
        return _pdf_layout(data, ocr=ocr, engine=engine)
    return _parsed_layout(parse(data, filename=filename, mime_type=mime, parsing=ParsingSettings(ocr=ocr)))


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
    ocr = {int(p["number"]) for p in layout["pages"] if p["source"] == "ocr" and int(p["number"]) in joined}
    confidence: dict[int, dict[str, float]] = {}
    for word in cast(list[dict[str, Any]], layout["words"]):
        page = int(word["page"])
        if page in ocr:
            key = fold(str(word["text"]))
            on_page = confidence.setdefault(page, {})
            on_page[key] = max(on_page.get(key, 0.0), float(word["conf"]))
    return Pages(joined, ocr, max(len(layout["pages"]), 1), confidence, layout)
