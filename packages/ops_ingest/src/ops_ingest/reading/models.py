# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""What a reading holds: the file's facts and, per page, how it was read, its text, blocks, words and form fields.

Boxes are `[x0, top, x1, bottom]` as fractions of the page from its top left, so a box means the same on a PDF page in
points, a scan in pixels and any resolution it is drawn at. Fields serialise in camelCase like the rest of the
package's models (`model_dump(by_alias=True)`).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

#: Part of every stored reading's key. Raised whenever the output for the same bytes and settings changes, so an old
#: reading is read again rather than served.
READER_VERSION = "reading-4"

OcrMode = Literal["off", "auto", "always"]
#: How a page was read: its text layer, OCR of the whole page, its text layer plus OCR of its picture areas, or not at
#: all (`unread_reason` says why).
PageSource = Literal["text", "ocr", "mixed", "none"]
BlockKind = Literal["title", "heading", "paragraph", "table"]
FieldKind = Literal["text", "checkbox", "choice", "signature"]
Box = list[float]

_LANGUAGE = re.compile(r"^[A-Za-z_]+(\+[A-Za-z_]+)*$")


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ReadingSettings(_Model):
    """The settings that change what is read from the same bytes, and so are part of a stored reading's key."""

    ocr: OcrMode = "auto"
    #: A Tesseract language, or several joined by `+` (`eng+fra`).
    language: str = "eng"

    @field_validator("language")
    @classmethod
    def _language(cls, value: str) -> str:
        if not _LANGUAGE.match(value):
            raise ValueError(f"not a Tesseract language: {value!r}")
        return value

    @property
    def key(self) -> str:
        return f"{self.ocr}:{self.language}"


class Line(_Model):
    text: str
    box: Box | None = None


class Cell(_Model):
    id: str
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    text: str
    box: Box | None = None
    #: The table's first row with any text, read as its header.
    header: bool = False


class Block(_Model):
    """One run of content in reading order. A paragraph keeps its lines (and their boxes) so the page's text can put
    each on its own line; a table keeps its cells."""

    id: str
    kind: BlockKind
    text: str
    box: Box | None = None
    #: Position in the page's reading order.
    order: int = 0
    #: For a title or heading: 1 is the largest size in the file.
    level: int | None = None
    lines: list[Line] = Field(default_factory=list[Line])
    cells: list[Cell] = Field(default_factory=list[Cell])
    caption: str | None = None
    #: The worksheet a spreadsheet table came from.
    sheet: str | None = None
    #: Whether the block came from the text layer or from OCR.
    read_by: Literal["text", "ocr"] = "text"
    #: An HTML block inside page furniture (navigation, banners, footers), or inside the main or article element. Kept
    #: in the reading so a cleaning change splits it again without reading the page again.
    furniture: bool = False
    main: bool = False


class Word(_Model):
    text: str
    box: Box
    #: 1.0 from a text layer, Tesseract's confidence (0 to 1) from OCR.
    confidence: float


class FormField(_Model):
    """A field of a fillable PDF form, read from the form dictionary: values typed into a form are not in the text
    layer."""

    name: str
    value: str
    kind: FieldKind
    page: int
    box: Box | None = None


class OcrQuality(_Model):
    mean: float
    #: Share of the OCR'd words with a confidence below `LOW_CONFIDENCE`.
    low_share: float
    words: int


class Page(_Model):
    number: int
    #: In points for a PDF, pixels for an image file, none for formats without pages.
    width: float | None = None
    height: float | None = None
    source: PageSource
    #: Share of the page covered by pictures, recorded so the mixed-page threshold can be checked on real files.
    image_share: float = 0.0
    #: The page's text in reading order, one line per line read.
    text: str = ""
    blocks: list[Block] = Field(default_factory=list[Block])
    words: list[Word] = Field(default_factory=list[Word])
    form_fields: list[FormField] = Field(default_factory=list[FormField])
    ocr: OcrQuality | None = None
    unread_reason: str | None = None
    warnings: list[str] = Field(default_factory=list[str])
    duration_ms: int = 0


class FileFacts(_Model):
    """What is known about a file before its pages are read."""

    filename: str
    mime_type: str
    size_bytes: int
    page_count: int
    title: str | None = None
    author: str | None = None
    created: str | None = None
    modified: str | None = None
    #: False for formats with no pages (DOCX, HTML, spreadsheets, text): all their content is stored as page 1, but a
    #: citation must not name a page.
    paged: bool = True
    #: Characters a parser dropped as page furniture.
    removed_chars: int = 0
    warnings: list[str] = Field(default_factory=list[str])


class UnreadPage(_Model):
    page: int
    reason: str


class Reading(_Model):
    reader_version: str = READER_VERSION
    settings: ReadingSettings
    facts: FileFacts
    pages: list[Page]
    duration_ms: int = 0

    @property
    def ocr_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.source in ("ocr", "mixed")]

    @property
    def unread(self) -> list[UnreadPage]:
        return [UnreadPage(page=p.number, reason=p.unread_reason or "") for p in self.pages if p.source == "none"]

    @property
    def form_fields(self) -> list[FormField]:
        return [f for p in self.pages for f in p.form_fields]


def page_text(blocks: list[Block]) -> str:
    """A page's text in reading order. A two-cell table row (a label and its value) puts each cell on its own line,
    because joined on one line a model copied the whole row into the value; a wider row is a record and stays on one
    line so its values stay together."""
    out: list[str] = []
    for block in blocks:
        if block.kind == "table":
            for row in sorted({c.row for c in block.cells}):
                texts = [c.text for c in sorted(block.cells, key=lambda c: c.col) if c.row == row and c.text]
                if len(texts) == 2:
                    out.extend(texts)
                elif texts:
                    out.append(" | ".join(texts))
        elif block.lines:
            out.extend(line.text for line in block.lines)
        elif block.text:
            out.append(block.text)
    return "\n".join(out)


ReadingErrorCode = Literal[
    "unsupported_format", "legacy_format", "too_large", "too_many_pages", "ocr_unavailable", "unreadable_file"
]


class ReadingError(ValueError):
    """A file that cannot be read at all, with a code the caller records as the reason. A page that cannot be read is
    not an error: it is listed with `source="none"` and its `unread_reason`."""

    def __init__(self, code: ReadingErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: ReadingErrorCode = code
