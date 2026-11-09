# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""A PDF read page by page: the text layer through pdfplumber, OCR where the page has no text layer or where pictures
cover enough of it, and the fields of a fillable form.

Text-layer words are grouped into lines (tops within 2 points, split where a gap is wider than three times the font
size, so two columns stay apart), lines into paragraphs where the gap to the next line is no more than 0.8 of a line's
height, and a line set larger than the body text is a heading. Heading levels and the body size are measured over the
whole file before any page is read, so a page read on its own (after a restart) gets the same levels as in one pass.
Table regions are cut out of the text so a table's cells are not read twice.
"""

from __future__ import annotations

import io
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any, cast

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import PdfminerException
from PIL import Image

from ops_ingest.reading.forms import page_fields
from ops_ingest.reading.images import (
    NOTHING_FOUND,
    OCR_OFF,
    Engines,
    as_words,
    ocr_blocks,
    ocr_page,
    ocr_words,
    quality,
)
from ops_ingest.reading.models import (
    Block,
    Box,
    Cell,
    FileFacts,
    Line,
    Page,
    ReadingError,
    ReadingSettings,
    Word,
    page_text,
)

MAX_PAGES = 2_000
OCR_RESOLUTION = 200
#: The most pixels a page is drawn at for OCR: 4,000 x 4,000, a letter page at about 450 DPI. A larger page is drawn
#: at a lower resolution, so a poster-sized page cannot exhaust memory.
MAX_RENDER_PIXELS = 16_000_000
#: Under `auto`, a page with a text layer whose pictures cover at least this share of it has its picture areas OCR'd.
#: Set from one sample (a half-scanned form at 25%) so a logo does not start OCR; each page records its share so the
#: line can be checked on real files.
MIXED_IMAGE_SHARE = 0.2
HEADING_RATIO = 1.15
TITLE_RATIO = 1.5
HEADING_MAX_CHARS = 150
_CAPTION = re.compile(r"^table\b", re.IGNORECASE)

Rect = tuple[float, float, float, float]


@dataclass
class _Segment:
    top: float
    bottom: float
    x0: float
    x1: float
    text: str
    size: float


@dataclass
class _Table:
    top: float
    x0: float
    box: Rect
    cells: list[Cell]


@dataclass
class _Sizes:
    body: float
    levels: dict[float, int] = field(default_factory=dict[float, int])


def _frac(box: Rect, width: float, height: float) -> Box:
    x0, top, x1, bottom = box
    return [round(x0 / width, 4), round(top / height, 4), round(x1 / width, 4), round(bottom / height, 4)]


def _centre_in(box: Rect, rects: list[Rect]) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in rects)


def _word_rect(word: dict[str, Any]) -> Rect:
    return (float(word["x0"]), float(word["top"]), float(word["x1"]), float(word["bottom"]))


def _segments(words: list[dict[str, Any]]) -> list[_Segment]:
    rows: list[list[dict[str, Any]]] = []
    for w in sorted(words, key=lambda w: (float(w["top"]), float(w["x0"]))):
        if rows and abs(float(rows[-1][0]["top"]) - float(w["top"])) <= 2:
            rows[-1].append(w)
        else:
            rows.append([w])
    groups: list[list[dict[str, Any]]] = []
    for row in rows:
        row.sort(key=lambda w: float(w["x0"]))
        current = [row[0]]
        for w in row[1:]:
            if float(w["x0"]) - float(current[-1]["x1"]) > 3 * float(w["size"]):
                groups.append(current)
                current = [w]
            else:
                current.append(w)
        groups.append(current)
    out: list[_Segment] = []
    for group in groups:
        text = " ".join(str(w["text"]) for w in group)
        chars = sum(len(str(w["text"])) for w in group) or 1
        size = sum(float(w["size"]) * len(str(w["text"])) for w in group) / chars
        out.append(
            _Segment(
                top=min(float(w["top"]) for w in group),
                bottom=max(float(w["bottom"]) for w in group),
                x0=min(float(w["x0"]) for w in group),
                x1=max(float(w["x1"]) for w in group),
                text=text,
                size=size,
            )
        )
    return out


def _tables(page: Any, number: int) -> list[_Table]:
    width, height = float(page.width), float(page.height)
    out: list[_Table] = []
    for t_index, found in enumerate(page.find_tables()):
        texts = cast(list[list[str | None]], found.extract())
        cells: list[Cell] = []
        header_row: int | None = None
        for r_index, row in enumerate(found.rows):
            raw = cast(list[Any], row.cells)
            for c_index, cell in enumerate(raw):
                if cell is None:
                    continue  # covered by a merged cell to its left
                span = 1
                while c_index + span < len(raw) and raw[c_index + span] is None:
                    span += 1
                text = " ".join((texts[r_index][c_index] or "").split())
                if text and header_row is None:
                    header_row = r_index
                rect = cast(Rect, tuple(float(v) for v in cell))
                cells.append(
                    Cell(
                        id=f"p{number}.t{t_index}.r{r_index}.c{c_index}",
                        row=r_index,
                        col=c_index,
                        col_span=span,
                        text=text,
                        box=_frac(rect, width, height),
                    )
                )
        if header_row is None:
            continue
        for cell in cells:
            cell.header = cell.row == header_row
        x0, top, x1, bottom = (float(v) for v in found.bbox)
        out.append(_Table(top=top, x0=x0, box=(x0, top, x1, bottom), cells=cells))
    return out


@dataclass
class _Layer:
    segments: list[_Segment]
    tables: list[_Table]
    words: list[dict[str, Any]]


def _layer(page: Any, number: int) -> _Layer:
    tables = _tables(page, number)
    words = [cast(dict[str, Any], w) for w in page.extract_words(extra_attrs=["size"])]
    rects = [t.box for t in tables]
    outside = [w for w in words if not _centre_in(_word_rect(w), rects)]
    return _Layer(_segments(outside) if outside else [], tables, words)


def _image_rects(page: Any) -> list[Rect]:
    width, height = float(page.width), float(page.height)
    out: list[Rect] = []
    for image in cast(list[dict[str, Any]], page.images):
        x0, top = max(0.0, float(image["x0"])), max(0.0, float(image["top"]))
        x1, bottom = min(width, float(image["x1"])), min(height, float(image["bottom"]))
        if x1 > x0 and bottom > top:
            out.append((x0, top, x1, bottom))
    return out


def _covered(rects: list[Rect], width: float, height: float) -> float:
    """The share of the page under at least one picture, overlaps counted once."""
    if not rects or width <= 0 or height <= 0:
        return 0.0
    xs = sorted({x for r in rects for x in (r[0], r[2])})
    ys = sorted({y for r in rects for y in (r[1], r[3])})
    area = 0.0
    for x0, x1 in pairwise(xs):
        for y0, y1 in pairwise(ys):
            if any(r[0] <= x0 and x1 <= r[2] and r[1] <= y0 and y1 <= r[3] for r in rects):
                area += (x1 - x0) * (y1 - y0)
    return round(area / (width * height), 4)


def _merged(rects: list[Rect]) -> list[Rect]:
    """Overlapping pictures as one area, so the same pixels are not OCR'd twice."""
    areas = list(rects)
    changed = True
    while changed:
        changed = False
        for i in range(len(areas)):
            for j in range(i + 1, len(areas)):
                a, b = areas[i], areas[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    areas[i] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                    del areas[j]
                    changed = True
                    break
            if changed:
                break
    return areas


class PdfFile:
    """An open PDF. `page(n)` reads one page; `facts` is known once it is open."""

    def __init__(self, data: bytes, *, filename: str, settings: ReadingSettings, engines: Engines) -> None:
        try:
            self._pdf = pdfplumber.open(io.BytesIO(data))
            count = len(self._pdf.pages)
        except (PdfminerException, PDFSyntaxError, ValueError, KeyError, TypeError) as exc:
            raise ReadingError("unreadable_file", f"{filename} is not a readable PDF: {exc}") from exc
        if count > MAX_PAGES:
            self._pdf.close()
            raise ReadingError("too_many_pages", f"{filename} has {count} pages; the limit is {MAX_PAGES}")
        meta = cast(dict[str, Any], self._pdf.metadata or {})  # pyright: ignore[reportUnknownMemberType]
        self.facts = FileFacts(
            filename=filename,
            mime_type="application/pdf",
            size_bytes=len(data),
            page_count=count,
            title=str(meta.get("Title") or "").strip() or None,
            author=str(meta.get("Author") or "").strip() or None,
            created=str(meta.get("CreationDate") or "") or None,
            modified=str(meta.get("ModDate") or "") or None,
        )
        self._settings = settings
        self._engines = engines
        self._sizes: _Sizes | None = None

    def close(self) -> None:
        self._pdf.close()

    def _measure(self) -> _Sizes:
        """The body text size (the size most characters are set in) and each heading size's level, over every page's
        text outside tables."""
        if self._sizes is None:
            counts: Counter[float] = Counter()
            segments: list[_Segment] = []
            for number, page in enumerate(self._pdf.pages, start=1):
                if page.chars:
                    found = _layer(page, number).segments
                    segments.extend(found)
                    counts.update({round(s.size, 1): len(s.text) for s in found})
            body = counts.most_common(1)[0][0] if counts else 0.0
            sizes = sorted(
                {round(s.size, 1) for s in segments if body and s.size >= body * HEADING_RATIO}, reverse=True
            )
            self._sizes = _Sizes(body=body, levels={size: i + 1 for i, size in enumerate(sizes)})
        return self._sizes

    def needs_ocr(self, number: int) -> bool:
        """Whether reading the page runs OCR under these settings: cheap, from the text layer and picture boxes only."""
        mode = self._settings.ocr
        if mode == "off":
            return False
        page = self._pdf.pages[number - 1]
        if mode == "always" or not page.chars:
            return True
        return _covered(_image_rects(page), float(page.width), float(page.height)) >= MIXED_IMAGE_SHARE

    def page(self, number: int) -> Page:
        started = time.perf_counter()
        page_obj = self._pdf.pages[number - 1]
        width, height = float(page_obj.width), float(page_obj.height)
        rects = _image_rects(page_obj)
        share = _covered(rects, width, height)
        fields = page_fields(
            page_obj.page_obj.attrs.get("Annots"),
            number,
            width=width,
            height=height,
            rotation=int(page_obj.rotation or 0),
        )
        mode = self._settings.ocr
        if mode == "always" or (not page_obj.chars and mode == "auto"):
            read = ocr_page(number, self._render(page_obj), self._engines.get(), width=width, height=height)
        elif not page_obj.chars:
            read = Page(number=number, width=width, height=height, source="none", unread_reason=OCR_OFF)
        else:
            read = self._text_page(
                page_obj, number, width=width, height=height, rects=rects if mode == "auto" else [], share=share
            )
        read.image_share = share
        read.form_fields = fields
        if read.source == "none" and read.unread_reason == NOTHING_FOUND and fields:
            read.warnings.append("The page has no text, but its form fields were read.")
        read.duration_ms = round((time.perf_counter() - started) * 1000)
        return read

    def _render(self, page: Any) -> Image.Image:
        """The page drawn for OCR at `OCR_RESOLUTION`, or lower when that would pass `MAX_RENDER_PIXELS`."""
        inches = float(page.width) * float(page.height) / (72 * 72)
        resolution = min(float(OCR_RESOLUTION), math.sqrt(MAX_RENDER_PIXELS / inches)) if inches > 0 else OCR_RESOLUTION
        return cast(Image.Image, page.to_image(resolution=math.floor(resolution)).original)

    def _text_page(
        self, page: Any, number: int, *, width: float, height: float, rects: list[Rect], share: float
    ) -> Page:
        sizes = self._measure()
        layer = _layer(page, number)
        blocks = self._blocks(layer, number, sizes, width, height)
        words = [
            Word(text=str(w["text"]), box=_frac(_word_rect(w), width, height), confidence=1.0) for w in layer.words
        ]
        mixed = bool(rects) and share >= MIXED_IMAGE_SHARE
        ocr = None
        if mixed:
            found = self._picture_words(page, rects, layer.words, width, height)
            ocr = quality(found)
            if found:
                extra = ocr_blocks(number, found, first_id=len(blocks))
                # Stable: text blocks keep their order, each OCR'd paragraph lands by where it starts on the page.
                blocks = sorted([*blocks, *extra], key=lambda b: b.box[1] if b.box else 0.0)
                words.extend(as_words(found))
        for i, block in enumerate(blocks):
            block.order = i
        return Page(
            number=number,
            width=width,
            height=height,
            source="mixed" if mixed else "text",
            text=page_text(blocks),
            blocks=blocks,
            words=words,
            ocr=ocr,
        )

    def _picture_words(
        self, page: Any, rects: list[Rect], text_words: list[dict[str, Any]], width: float, height: float
    ) -> list[tuple[Any, Box]]:
        """Words OCR'd from the page's picture areas, leaving out any that sit on a text-layer word: a scan carrying
        its own OCR text layer would otherwise be read twice."""
        engine = self._engines.get()
        drawn = self._render(page)
        sx, sy = drawn.width / width, drawn.height / height
        taken = [_word_rect(w) for w in text_words]
        out: list[tuple[Any, Box]] = []
        for x0, top, x1, bottom in _merged(rects):
            crop = drawn.crop((round(x0 * sx), round(top * sy), round(x1 * sx), round(bottom * sy)))
            region = [x0 / width, top / height, x1 / width, bottom / height]
            for word, box in ocr_words(engine, crop, region):
                on_page = (box[0] * width, box[1] * height, box[2] * width, box[3] * height)
                if not _centre_in(on_page, taken):
                    out.append((word, box))
        return out

    def _blocks(self, layer: _Layer, number: int, sizes: _Sizes, width: float, height: float) -> list[Block]:
        events: list[tuple[float, float, _Segment | _Table]] = [(s.top, s.x0, s) for s in layer.segments]
        events.extend((t.top, t.x0, t) for t in layer.tables)
        events.sort(key=lambda e: (e[0], e[1]))
        blocks: list[Block] = []
        paragraph: list[_Segment] = []
        previous: _Segment | None = None

        def add(**values: Any) -> None:
            blocks.append(Block(id=f"p{number}.b{len(blocks)}", **values))

        def flush() -> None:
            if paragraph:
                lines = [Line(text=s.text, box=_frac((s.x0, s.top, s.x1, s.bottom), width, height)) for s in paragraph]
                rect = (
                    min(s.x0 for s in paragraph),
                    min(s.top for s in paragraph),
                    max(s.x1 for s in paragraph),
                    max(s.bottom for s in paragraph),
                )
                add(
                    kind="paragraph",
                    text=" ".join(s.text for s in paragraph),
                    box=_frac(rect, width, height),
                    lines=lines,
                )
                paragraph.clear()

        for _, _, item in events:
            if isinstance(item, _Table):
                caption = paragraph.pop().text if paragraph and _CAPTION.match(paragraph[-1].text) else None
                flush()
                text = "\n".join(c.text for c in item.cells if c.text)
                add(kind="table", text=text, box=_frac(item.box, width, height), cells=item.cells, caption=caption)
                previous = None
                continue
            size = round(item.size, 1)
            if size in sizes.levels and len(item.text) <= HEADING_MAX_CHARS:
                flush()
                kind = "title" if number == 1 and item.size >= sizes.body * TITLE_RATIO else "heading"
                rect = (item.x0, item.top, item.x1, item.bottom)
                add(kind=kind, text=item.text, box=_frac(rect, width, height), level=sizes.levels[size])
                previous = None
                continue
            line_height = max(item.bottom - item.top, 1.0)
            if previous is not None and item.top - previous.bottom > 0.8 * line_height:
                flush()
            paragraph.append(item)
            previous = item
        flush()
        return blocks
