# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The shapes ops_extract reads and builds, named once: a file's layout, a field's box, and what a team writes on a
document type (a field, a check across fields, a layout template). A read's scored answer is still `Json`.

A key a save check proves (`request_of`, `templates.problems`, `rules.problems`) has its type here; a key no check
proves, or one a team defines the values of, stays `JsonValue` and is narrowed where it is read, so a document saved
with an odd value is read and refused exactly as before. A stored document is read into these with
`ops_store.documents.stored`, which keeps the keys a shape does not name, so writing one back loses nothing."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from ops_service_kit.http import JsonValue

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
    """A layout template as `ops_extract.templates.suggest` drafts it."""

    id: str
    pages: list[TemplatePage]


class FieldDefinition(TypedDict):
    """A field a document type version (or an extraction request) asks for. `request_of` proves the key is text when
    it is saved. Its rules (`pattern`, `emptyWhen`, `keyField`, `clean`) are checked when saved too, but a type saved
    before a rule was checked, or edited by hand, may hold another value, so they are narrowed where they are read
    with the rest of the team's keys."""

    key: str
    label: NotRequired[JsonValue]
    # One of FIELD_TYPES, or empty for text.
    type: NotRequired[JsonValue]
    description: NotRequired[JsonValue]
    required: NotRequired[JsonValue]
    alwaysReview: NotRequired[JsonValue]
    keyField: NotRequired[JsonValue]
    reviewBelow: NotRequired[JsonValue]
    # MDY or DMY, set on every date field from its version.
    dateOrder: NotRequired[JsonValue]
    # An enum's values, the team's own.
    options: NotRequired[JsonValue]
    pattern: NotRequired[JsonValue]
    emptyWhen: NotRequired[JsonValue]
    clean: NotRequired[JsonValue]


class Check(TypedDict):
    """A check across a version's fields (`ops_extract.rules`): `rules.problems` proves the kind when it is saved."""

    id: JsonValue
    kind: str
    # sum: the parts and the field they add up to.
    fields: NotRequired[JsonValue]
    equals: NotRequired[JsonValue]
    tolerance: NotRequired[JsonValue]
    # before: the field that must not come after the other.
    earlier: NotRequired[JsonValue]
    later: NotRequired[JsonValue]


class SavedAnchor(TypedDict):
    # Any value whose text is not blank; `templates.problems` reads it as text.
    text: JsonValue
    box: Rect
    required: NotRequired[JsonValue]


class SavedTemplatePage(TypedDict):
    # Numbered from 1; a page without one is page 1.
    page: NotRequired[int]
    anchors: list[SavedAnchor]
    # `templates.problems` reads any empty value as no zones ("", {}, 0, false), so each is read the same way; a zone
    # is {field, box}.
    zones: NotRequired[JsonValue]


class SavedTemplate(TypedDict):
    """A layout template saved on a document type version, as `templates.problems` lets it be saved. One carried to a
    version that lacks a field it reads carries `needsRebuild` and is never matched."""

    id: str
    pages: list[SavedTemplatePage]
    # Read for truth only, as every reader of a saved template reads it.
    needsRebuild: NotRequired[JsonValue]
