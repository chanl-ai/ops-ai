# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The shapes ops_extract builds in process, named once: a file's layout, a field's box and a drafted template.

What a team writes on a document type (its fields, templates and checks) and what is stored for a read (each field's
result, the model's answer) are read as `Json` from `ops_service_kit.http` through `ops_service_kit.narrow`: a team
may add keys this package does not read and a row stored before a key existed lacks it, and validating either into a
TypedDict would drop or reject keys the stored JSON must keep."""

from __future__ import annotations

from typing import NotRequired, TypedDict

# [x0, top, x1, bottom] as fractions of the page from its top left, the reader's own boxes (`ops_ingest.reading`).
Rect = list[float]


class LayoutPage(TypedDict):
    number: int
    width: float | None
    height: float | None
    source: str


class LayoutCell(TypedDict):
    id: str
    row: int
    col: int
    rowSpan: int
    colSpan: int
    text: str
    box: Rect | None


class LayoutBlock(TypedDict):
    id: str
    page: int
    kind: str
    text: str
    box: Rect | None
    order: int
    # Only on a table.
    cells: NotRequired[list[LayoutCell]]


class LayoutWord(TypedDict):
    page: int
    text: str
    box: Rect
    conf: float


class Layout(TypedDict):
    """A file's layout (`ops_extract.layout.layout_of`), built from its reading each time and never stored."""

    engine: str
    pages: list[LayoutPage]
    blocks: list[LayoutBlock]
    words: list[LayoutWord]


class Box(TypedDict):
    """Where a field's value is on its page, one per line: fractions of the page from the top left."""

    page: int
    x: float
    y: float
    w: float
    h: float


class Located(TypedDict):
    """A field's boxes and the ids of the layout blocks (or table cells) its words are in."""

    boxes: list[Box]
    blocks: list[str]


class TemplateAnchor(TypedDict):
    """A label printed on the form, where the template expects it; one not `required` may be missing."""

    text: str
    box: Rect
    required: NotRequired[bool]


class TemplateZone(TypedDict):
    """Where a field's value is printed."""

    field: str
    box: Rect


class TemplatePage(TypedDict):
    page: int
    anchors: list[TemplateAnchor]
    zones: list[TemplateZone]


class Template(TypedDict):
    """A layout template as `ops_extract.templates.suggest` drafts it. A saved one is the team's JSON on a document type
    version, read key by key, as it may carry `needsRebuild` and keys added later."""

    id: str
    pages: list[TemplatePage]
