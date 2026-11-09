# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The fields of a fillable PDF form, read from each page's widget annotations.

Values typed into a form live in the form dictionary, not the page's text layer, so a text reader sees only the labels.
A widget's name, type, value and flags may be set on the widget or inherited from its parent field, so each is looked
up the parent chain; a field's full name is its parents' names joined with dots, as the PDF standard defines it.
"""

from __future__ import annotations

from typing import Any, cast

from pdfminer.pdftypes import PDFObjRef, resolve1
from pdfminer.psparser import PSLiteral
from pdfminer.utils import decode_text

from ops_ingest.reading.models import FieldKind, FormField

# Field flags (PDF 32000-1, table 226): a button that is a radio group, or a push button with no value.
_RADIO = 1 << 15
_PUSH_BUTTON = 1 << 16
# Deeper than any real form; stops a malformed file whose parents loop.
_MAX_DEPTH = 32


def _text(value: object) -> str:
    value = resolve1(value)
    if isinstance(value, bytes):
        return decode_text(value)
    if isinstance(value, PSLiteral):
        return str(value.name)
    if isinstance(value, list):
        return ", ".join(_text(v) for v in cast(list[object], value))
    return "" if value is None else str(value)


def _chain(widget: dict[str, Any], objid: int | None) -> list[dict[str, Any]]:
    """The widget, then its parent field, then that field's parent, up to the top. Each object is visited once and the
    walk is capped, so a malformed file whose parents loop still ends."""
    out: list[dict[str, Any]] = []
    seen: set[int] = set() if objid is None else {objid}
    node: dict[str, Any] | None = widget
    while node is not None and len(out) < _MAX_DEPTH:
        out.append(node)
        ref = node.get("Parent")
        if isinstance(ref, PDFObjRef):
            if ref.objid in seen:
                break
            seen.add(ref.objid)
        parent = resolve1(ref)
        node = cast(dict[str, Any], parent) if isinstance(parent, dict) else None
    return out


def _inherited(chain: list[dict[str, Any]], key: str) -> object:
    for node in chain:
        if key in node:
            return node[key]
    return None


def _kind(field_type: str, flags: int) -> FieldKind | None:
    match field_type:
        case "Tx":
            return "text"
        case "Ch":
            return "choice"
        case "Sig":
            return "signature"
        case "Btn" if flags & _PUSH_BUTTON:
            return None
        case "Btn" if flags & _RADIO:
            return "choice"
        case "Btn":
            return "checkbox"
        case _:
            return None


def _value(kind: FieldKind, chain: list[dict[str, Any]]) -> str:
    raw = _inherited(chain, "V")
    if kind == "checkbox":
        state = _text(raw if raw is not None else chain[0].get("AS"))
        return "checked" if state and state != "Off" else "unchecked"
    if kind == "signature":
        return "signed" if raw is not None else ""
    value = _text(raw)
    return "" if value == "Off" else value


def _box(rect: object, *, width: float, height: float, rotation: int) -> list[float] | None:
    """A widget's `/Rect` (PDF units, origin bottom left) as fractions of the page as shown, turned with the page."""
    values = resolve1(rect)
    if not isinstance(values, list) or len(cast(list[object], values)) != 4:
        return None
    try:
        a, b, c, d = (float(cast(float, resolve1(v))) for v in cast(list[object], values))
    except (TypeError, ValueError):
        return None
    points = [(a, b), (c, d)]
    turns = (rotation % 360) // 90
    for i in range(turns):
        side = width if i == turns % 2 else height
        points = [(y, side - x) for x, y in points]
    (x0, y0), (x1, y1) = points
    left, right, low, high = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    return [
        round(left / width, 4),
        round((height - high) / height, 4),
        round(right / width, 4),
        round((height - low) / height, 4),
    ]


def page_fields(annots: object, number: int, *, width: float, height: float, rotation: int = 0) -> list[FormField]:
    """The form fields whose widgets sit on one page, given the page's raw `/Annots`. Each annotation is resolved one
    level only: pdfplumber's own `page.annots` resolves `/Kids` recursively and never ends on a file whose kids loop.
    A field with several widgets (a radio group) is listed once, at its first widget."""
    fields: list[FormField] = []
    seen: set[str] = set()
    listed = resolve1(annots)
    for ref in cast(list[object], listed) if isinstance(listed, list) else []:
        data = resolve1(ref)
        if not isinstance(data, dict):
            continue
        widget = cast(dict[str, Any], data)
        if _text(widget.get("Subtype")) != "Widget":
            continue
        chain = _chain(widget, ref.objid if isinstance(ref, PDFObjRef) else None)
        names = [_text(node["T"]) for node in reversed(chain) if "T" in node]
        kind = _kind(_text(_inherited(chain, "FT")), int(cast(int, resolve1(_inherited(chain, "Ff")) or 0)))
        name = ".".join(n for n in names if n)
        if kind is None or not name or name in seen:
            continue
        seen.add(name)
        box = _box(widget.get("Rect"), width=width, height=height, rotation=rotation)
        fields.append(FormField(name=name, value=_value(kind, chain), kind=kind, page=number, box=box))
    return fields
