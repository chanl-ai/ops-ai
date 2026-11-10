# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Formats without a page layout (DOCX, XLSX, CSV, HTML, text, Markdown) read through their parsers into pages of
blocks without boxes, and any reading turned back into the `ParsedDocument` that `split` takes.

The round trip keeps what splitting depends on: heading levels (so heading paths rebuild the same), paragraph breaks,
tables with their header row, caption and worksheet, and page numbers.
"""

from __future__ import annotations

from ops_ingest.models import ParsedDocument, ParsingSettings, SourceMetadata, Table
from ops_ingest.parsers import parse
from ops_ingest.parsers.builder import DocumentBuilder
from ops_ingest.reading.models import Block, Cell, FileFacts, Page, Reading, page_text

#: The section a filled form's fields are listed under, so typed values are searchable.
FORM_FIELDS_HEADING = "Form fields"


def _table_block(table: Table, page: int, index: int) -> Block:
    cells = [
        Cell(id=f"p{page}.b{index}.r{r}.c{c}", row=r, col=c, text=text, header=r == 0)
        for r, row in enumerate([table.headers, *table.rows])
        for c, text in enumerate(row)
    ]
    text = "\n".join(c.text for c in cells if c.text)
    return Block(id=f"p{page}.b{index}", kind="table", text=text, cells=cells, caption=table.caption, sheet=table.sheet)


class ParsedFile:
    """A file read by its format's parser. Every page is built when the file is opened: these formats are small and
    have no OCR."""

    def __init__(self, data: bytes, *, filename: str, mime_type: str | None) -> None:
        doc = parse(data, filename=filename, mime_type=mime_type, parsing=ParsingSettings(ocr=False), mark=True)
        by_page: dict[int, list[Block]] = {}

        def add(page: int, **values: object) -> None:
            on_page = by_page.setdefault(page, [])
            on_page.append(Block.model_validate({"id": f"p{page}.b{len(on_page)}", **values}))

        for section in doc.sections:
            page = section.page or 1
            if section.heading_path:
                level = max(section.level, 1)
                marks = {"furniture": section.furniture, "main": section.main}
                add(page, kind="heading", text=section.heading_path[-1], level=level, **marks)
            for block in section.blocks:
                at = block.page or page
                if isinstance(block, Table):
                    on_page = by_page.setdefault(at, [])
                    table = _table_block(block, at, len(on_page))
                    table.furniture, table.main = block.furniture, block.main
                    on_page.append(table)
                else:
                    add(at, kind="paragraph", text=block.text, furniture=block.furniture, main=block.main)
        count = max([*by_page, doc.source.page_count or 1])
        self._pages: list[Page] = []
        for number in range(1, count + 1):
            blocks = by_page.get(number, [])
            for i, block in enumerate(blocks):
                block.order = i
            self._pages.append(Page(number=number, source="text", text=page_text(blocks), blocks=blocks))
        self.facts = FileFacts(
            filename=filename,
            mime_type=doc.source.mime_type,
            size_bytes=len(data),
            page_count=count,
            title=doc.source.title,
            author=doc.source.author,
            created=doc.source.created,
            modified=doc.source.modified,
            paged=bool(doc.source.page_count),
            removed_chars=doc.removed_chars,
            warnings=list(doc.warnings),
        )

    def needs_ocr(self, number: int) -> bool:
        del number
        return False

    def page(self, number: int) -> Page:
        return self._pages[number - 1].model_copy(deep=True)

    def close(self) -> None:
        return None


def _rows(cells: list[Cell]) -> list[list[str]]:
    """A table's cells as rows of text, a merged cell's covered columns left empty."""
    width = max((c.col + c.col_span for c in cells), default=0)
    rows: dict[int, list[str]] = {}
    for cell in cells:
        rows.setdefault(cell.row, [""] * width)[cell.col] = cell.text
    return [rows[r] for r in sorted(rows)]


def to_parsed_document(
    reading: Reading,
    *,
    fields: dict[str, str] | None = None,
    keep_tables: bool = True,
    furniture: bool = False,
    main_content: bool = False,
) -> ParsedDocument:
    """The reading as the `ParsedDocument` that `split` takes: titles and headings by level become heading paths,
    paragraphs and tables stay as read, and a form's fields become a "Form fields" section of `name: value` lines.
    `furniture` drops the blocks the reading marked as page furniture; `main_content` keeps only the main or article
    element's blocks when the page has one. What either drops is counted as removed."""
    builder = DocumentBuilder()
    paged = reading.facts.paged
    has_main = main_content and any(b.main for p in reading.pages for b in p.blocks)
    dropped = 0
    for page in reading.pages:
        at = page.number if paged else None
        for block in page.blocks:
            if (furniture and block.furniture) or (has_main and not block.main and block.kind != "title"):
                dropped += len(block.text)
                continue
            match block.kind:
                case "title" | "heading":
                    builder.heading(block.text, block.level or 1, at)
                case "paragraph":
                    builder.paragraph(block.text, at)
                case "table":
                    rows = [r for r in _rows(block.cells) if any(t.strip() for t in r)]
                    if rows:
                        builder.table(
                            rows[0],
                            rows[1:],
                            page=at,
                            caption=block.caption,
                            sheet=block.sheet,
                            keep_as_table=keep_tables,
                        )
        if page.source == "none":
            builder.pages_without_text.append(page.number)
            builder.warnings.append(f"Page {page.number} was not read: {page.unread_reason}.")
        elif page.source in ("ocr", "mixed"):
            builder.ocr_pages.append(page.number)
        builder.warnings.extend(page.warnings)
    form = reading.form_fields
    if form:
        at = form[0].page if paged else None
        builder.heading(FORM_FIELDS_HEADING, 1, at)
        builder.paragraph("\n".join(f"{f.name}: {f.value}" for f in form), at)
    builder.warnings[:0] = reading.facts.warnings
    builder.removed_chars = reading.facts.removed_chars + dropped
    facts = reading.facts
    source = SourceMetadata(
        filename=facts.filename,
        mime_type=facts.mime_type,
        size_bytes=facts.size_bytes,
        title=facts.title,
        author=facts.author,
        created=facts.created,
        modified=facts.modified,
        page_count=facts.page_count if paged else None,
        fields=fields or {},
    )
    return builder.build(title=facts.title, source=source)
