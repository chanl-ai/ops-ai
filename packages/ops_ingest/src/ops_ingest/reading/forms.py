# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The fields of a fillable PDF form, read from each page's widget annotations.

Values typed into a form live in the form dictionary, not the page's text layer, so a text reader sees only the labels.
A widget's name, type, value and flags may be set on the widget or inherited from its parent field, so each is looked
up the parent chain; a field's full name is its parents' names joined with dots, as the PDF standard defines it.
"""

from __future__ import annotations

from typing import Any, cast

from pdfminer.pdftypes import resolve1
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


def _chain(widget: dict[str, Any]) -> list[dict[str, Any]]:
    """The widget, then its parent field, then that field's parent, up to the top."""
    out: list[dict[str, Any]] = []
    node: dict[str, Any] | None = widget
    while node is not None and len(out) < _MAX_DEPTH:
        out.append(node)
        parent = resolve1(node.get("Parent"))
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


def page_fields(annots: list[dict[str, Any]], number: int, width: float, height: float) -> list[FormField]:
    """The form fields whose widgets sit on one page, given pdfplumber's `page.annots`. A field with several widgets
    (a radio group) is listed once, at its first widget."""
    fields: list[FormField] = []
    seen: set[str] = set()
    for annot in annots:
        data = cast(dict[str, Any], annot.get("data") or {})
        if _text(data.get("Subtype")) != "Widget":
            continue
        chain = _chain(data)
        names = [_text(node["T"]) for node in reversed(chain) if "T" in node]
        kind = _kind(_text(_inherited(chain, "FT")), int(cast(int, resolve1(_inherited(chain, "Ff")) or 0)))
        name = ".".join(n for n in names if n)
        if kind is None or not name or name in seen:
            continue
        seen.add(name)
        box = [
            round(float(annot["x0"]) / width, 4),
            round(float(annot["top"]) / height, 4),
            round(float(annot["x1"]) / width, 4),
            round(float(annot["bottom"]) / height, 4),
        ]
        fields.append(FormField(name=name, value=_value(kind, chain), kind=kind, page=number, box=box))
    return fields
