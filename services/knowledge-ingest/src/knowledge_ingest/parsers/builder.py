# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Builds a `ParsedDocument` from a stream of headings, paragraphs and tables in reading order."""

from __future__ import annotations

from knowledge_ingest.models import Paragraph, ParsedDocument, Section, SourceMetadata, Table


class DocumentBuilder:
    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []
        self._sections: list[Section] = [Section()]
        self.warnings: list[str] = []
        self.ocr_pages: list[int] = []
        self.pages_without_text: list[int] = []
        self.removed_chars = 0

    def heading(self, text: str, level: int, page: int | None = None) -> None:
        text = " ".join(text.split())
        if not text:
            return
        level = max(1, level)
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, text))
        self._sections.append(Section(heading_path=[t for _, t in self._stack], level=level, blocks=[], page=page))

    def paragraph(self, text: str, page: int | None = None) -> None:
        text = text.strip()
        if text:
            self._current(page).blocks.append(Paragraph(text=text, page=page))

    def table(
        self,
        headers: list[str],
        rows: list[list[str]],
        *,
        page: int | None = None,
        caption: str | None = None,
        sheet: str | None = None,
        keep_as_table: bool = True,
    ) -> None:
        headers = [" ".join(h.split()) for h in headers]
        rows = [[" ".join(c.split()) for c in row] for row in rows if any(c.strip() for c in row)]
        if not headers and not rows:
            return
        table = Table(headers=headers, rows=rows, caption=caption, page=page, sheet=sheet)
        if keep_as_table:
            self._current(page).blocks.append(table)
        else:
            self.paragraph(table.as_text(), page)

    def _current(self, page: int | None) -> Section:
        section = self._sections[-1]
        if section.page is None:
            section.page = page
        return section

    def build(self, *, title: str | None, source: SourceMetadata) -> ParsedDocument:
        sections = [s for s in self._sections if s.blocks or s.heading_path]
        first_heading = next((s.heading_path[0] for s in sections if s.heading_path), None)
        resolved = title or source.title or first_heading or source.filename
        return ParsedDocument(
            title=resolved,
            source=source,
            sections=sections,
            ocr_pages=self.ocr_pages,
            pages_without_text=self.pages_without_text,
            removed_chars=self.removed_chars,
            warnings=self.warnings,
        )
