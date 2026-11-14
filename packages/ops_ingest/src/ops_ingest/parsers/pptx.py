# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""PowerPoint decks (.pptx). Each slide is one page, so a citation's page number is the slide number.

A slide reads as its title, then its text boxes, tables and charts from top to bottom and left to right, then its
speaker notes under a "Notes" heading. A chart reads as its title and a table of categories by series. Pictures carry
no text here; a slide with only pictures is an empty page in its place, so later slides keep their numbers.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from typing import Any, Literal

from pptx import Presentation
from pptx.exc import PackageNotFoundError
from pptx.shapes.group import GroupShape

from ops_ingest.models import ParsedDocument, ParsingSettings, SourceMetadata
from ops_ingest.parsers.builder import DocumentBuilder

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
NOTES_HEADING = "Notes"


class UnreadableDeckError(ValueError):
    code: Literal["unreadable_file"] = "unreadable_file"


def _in_reading_order(shapes: Any) -> Iterator[Any]:
    """Shapes top to bottom, then left to right; a group's shapes in their own order where the group sits."""
    for shape in sorted(shapes, key=lambda s: (s.top or 0, s.left or 0)):
        if isinstance(shape, GroupShape):
            yield from _in_reading_order(shape.shapes)
        else:
            yield shape


def _chart(builder: DocumentBuilder, chart: Any, page: int, keep: bool) -> None:
    if chart.has_title and chart.chart_title.has_text_frame:
        builder.paragraph(chart.chart_title.text_frame.text, page)
    plot = chart.plots[0] if len(chart.plots) else None
    categories = [str(c) for c in plot.categories] if plot is not None else []
    series = list(chart.series)
    if not series:
        return
    if not categories:
        # A scatter or bubble chart has no categories: its series names are what it says.
        builder.paragraph(", ".join(s.name for s in series if s.name), page)
        return
    rows: list[list[str]] = []
    for i, category in enumerate(categories):
        values = [s.values[i] if i < len(s.values) else None for s in series]
        rows.append([category, *("" if v is None else f"{v:g}" for v in values)])
    builder.table(["", *(s.name or "" for s in series)], rows, page=page, keep_as_table=keep)


def _slide(builder: DocumentBuilder, slide: Any, page: int, keep: bool) -> None:
    title_shape = slide.shapes.title
    title = title_shape.text_frame.text if title_shape is not None and title_shape.has_text_frame else ""
    body = [s for s in _in_reading_order(slide.shapes) if title_shape is None or s.shape_id != title_shape.shape_id]
    notes = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
    has_text = any((s.has_text_frame and s.text_frame.text.strip()) or s.has_table or s.has_chart for s in body)
    if not (title.strip() or has_text or notes.strip()):
        return
    # Every slide opens a section, so a slide without a title never adds its text to the slide before it.
    builder.heading(title or f"Slide {page}", 1, page)
    for shape in body:
        if shape.has_table:
            cells = [[cell.text for cell in row.cells] for row in shape.table.rows]
            if cells:
                builder.table(cells[0], cells[1:], page=page, keep_as_table=keep)
        elif shape.has_chart:
            _chart(builder, shape.chart, page, keep)
        elif shape.has_text_frame:
            builder.paragraph(shape.text_frame.text, page)
    if notes.strip():
        builder.heading(NOTES_HEADING, 2, page)
        builder.paragraph(notes, page)


def parse_pptx(
    data: bytes,
    *,
    filename: str,
    parsing: ParsingSettings | None = None,
    fields: dict[str, str] | None = None,
) -> ParsedDocument:
    parsing = parsing or ParsingSettings()
    try:
        prs = Presentation(io.BytesIO(data))
    except (zipfile.BadZipFile, PackageNotFoundError, KeyError) as exc:
        raise UnreadableDeckError(f"{filename} is not a PowerPoint file that can be opened: {exc}") from exc
    builder = DocumentBuilder()
    for number, slide in enumerate(prs.slides, start=1):
        _slide(builder, slide, number, parsing.tables)
    props = prs.core_properties
    title = props.title or None
    source = SourceMetadata(
        filename=filename,
        mime_type=PPTX_MIME,
        size_bytes=len(data),
        title=title,
        author=props.author or None,
        created=props.created.isoformat() if props.created else None,
        modified=props.modified.isoformat() if props.modified else None,
        # Pages are slides, including empty ones at the end, so slide numbers hold.
        page_count=len(prs.slides) or None,
        fields=fields or {},
    )
    return builder.build(title=title, source=source)
