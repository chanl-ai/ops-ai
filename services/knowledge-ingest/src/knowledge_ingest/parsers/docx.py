# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Word documents. Paragraphs and tables are read in body order so a table stays under its heading."""

from __future__ import annotations

import io
import re

from docx import Document
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph

from knowledge_ingest.models import ParsedDocument, ParsingSettings, SourceMetadata
from knowledge_ingest.parsers.builder import DocumentBuilder

_HEADING_STYLE = re.compile(r"^heading\s*(\d)$", re.IGNORECASE)
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _heading_level(paragraph: DocxParagraph) -> int | None:
    style = paragraph.style
    name = (style.name or "") if style is not None else ""
    if name.lower() == "title":
        return 1
    match = _HEADING_STYLE.match(name)
    return int(match.group(1)) if match else None


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

    for block in document.iter_inner_content():
        if isinstance(block, DocxParagraph):
            level = _heading_level(block)
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
