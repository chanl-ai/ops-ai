# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Word documents. Paragraphs and tables are read in body order so a table stays under its heading."""

from __future__ import annotations

import io
import re

from docx import Document
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

from ops_ingest.models import ParsedDocument, ParsingSettings, SourceMetadata
from ops_ingest.parsers.builder import DocumentBuilder

_HEADING_STYLE = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)
# A numbered line such as "2. Open risks" or "3) Next steps".
_NUMBERED = re.compile(r"^\d{1,2}(\.\d{1,2})*[.)]?\s+\S")
# A line read as a heading in a file with no heading styles is at most this long and does not end like a sentence.
_INFERRED_MAX_CHARS = 80
_INFERRED_MAX_WORDS = 10
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _heading_level(paragraph: DocxParagraph) -> int | None:
    style = paragraph.style
    name = (style.name or "") if style is not None else ""
    if name.lower() == "title":
        return 1
    match = _HEADING_STYLE.match(name)
    return int(match.group(1)) if match else None


def _bold(paragraph: DocxParagraph) -> bool:
    """Every run with text is bold, set on the run or on its character or paragraph style."""
    runs = [r for r in paragraph.runs if r.text.strip()]
    if not runs:
        return False
    style_bold = bool(paragraph.style is not None and paragraph.style.font.bold)
    return all(r.bold or (r.bold is None and (style_bold or bool(r.style.font.bold))) for r in runs)


def _inferred_heading(paragraph: DocxParagraph) -> bool:
    """A short line written as a heading without a heading style: all bold, or numbered, and not ending like a
    sentence. Used only in a file that has no heading styles at all, so a styled file keeps exactly its own headings."""
    text = " ".join(paragraph.text.split())
    if not text or len(text) > _INFERRED_MAX_CHARS or len(text.split()) > _INFERRED_MAX_WORDS:
        return False
    if text[-1] in ".,;:!?":
        return False
    return _bold(paragraph) or bool(_NUMBERED.match(text))


def _table_rows(table: DocxTable) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        cells: list[str] = []
        previous: object = None
        for cell in row.cells:
            # Horizontally merged cells are returned once per grid column; keep one copy.
            if cell._tc is previous:  # pyright: ignore[reportPrivateUsage]
                continue
            previous = cell._tc  # pyright: ignore[reportPrivateUsage]
            cells.append(cell.text.strip())
        rows.append(cells)
    return rows


def parse_docx(
    data: bytes,
    *,
    filename: str,
    parsing: ParsingSettings | None = None,
    fields: dict[str, str] | None = None,
) -> ParsedDocument:
    parsing = parsing or ParsingSettings()
    document = Document(io.BytesIO(data))
    builder = DocumentBuilder()
    styled = any(_heading_level(p) is not None for p in document.paragraphs)

    for block in document.iter_inner_content():
        if isinstance(block, DocxParagraph):
            level = _heading_level(block)
            if level is None and not styled and _inferred_heading(block):
                level = 1
            if level is not None:
                builder.heading(block.text, level)
            else:
                builder.paragraph(block.text)
        else:
            rows = _table_rows(block)
            if rows:
                builder.table(rows[0], rows[1:], keep_as_table=parsing.tables)

    props = document.core_properties
    source = SourceMetadata(
        filename=filename,
        mime_type=DOCX_MIME,
        size_bytes=len(data),
        title=props.title or None,
        author=props.author or None,
        created=props.created.isoformat() if props.created else None,
        modified=props.modified.isoformat() if props.modified else None,
        fields=fields or {},
    )
    return builder.build(title=props.title or None, source=source)
