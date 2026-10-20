"""A case's fields as the case page shows them (c-291): each with its label, type and display text, in its case type's
order. The field types are the extraction field types (`ops_contracts.field_values.FIELD_TYPES`, which a document type
declares), plus `file` (a Files id) and `link` (a URL), so a field read from a document keeps its type on the case.
Display text is formatted here, on the server, so no client formats a bank's money or dates its own way."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

from ops_contracts.field_values import FIELD_TYPES, normalise
from ops_service_kit.errors import Unprocessable

CASE_FIELD_TYPES = (*FIELD_TYPES, "file", "link")
KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
MAX_FIELDS = 50


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    type: str
    required: bool = False
    options: tuple[str, ...] = ()


def specs_of(raw: Any) -> list[FieldSpec]:
    """A case type's `fields`, checked: a list of {key, label, type, required?, options?} with unique keys."""
    if not isinstance(raw, list):
        raise Unprocessable("A case type's fields are a list.", code="case_type_invalid")
    items = cast(list[Any], raw)
    if len(items) > MAX_FIELDS:
        raise Unprocessable(f"A case type holds at most {MAX_FIELDS} fields.", code="case_type_invalid")
    out: list[FieldSpec] = []
    for item in items:
        f = cast(dict[str, Any], item) if isinstance(item, dict) else {}
        key, kind = str(f.get("key") or ""), str(f.get("type") or "text")
        if not KEY.match(key) or key in {s.key for s in out}:
            raise Unprocessable(f"Field key {key!r} is missing, not a name, or used twice.", code="case_type_invalid")
        if kind not in CASE_FIELD_TYPES:
            raise Unprocessable(
                f"Field {key} has type {kind}; use one of {', '.join(CASE_FIELD_TYPES)}.", code="case_type_invalid"
            )
        options = tuple(str(o) for o in cast(list[Any], f.get("options") or []))
        if kind == "enum" and not options:
            raise Unprocessable(f"Field {key} is a choice with no options.", code="case_type_invalid")
        out.append(FieldSpec(key, str(f.get("label") or key), kind, bool(f.get("required")), options))
    return out


def display(spec: FieldSpec, value: Any) -> str:
    """The value as a person reads it: money and numbers grouped, a date as ISO, anything unreadable as given."""
    if value is None or value == "":
        return ""
    if spec.type in ("number", "money", "date", "enum"):
        canonical, _ = normalise({"type": spec.type, "options": list(spec.options)}, value)
        if canonical is None:
            return str(value)
        if spec.type == "money":
            return f"{float(canonical):,.2f}"
        if spec.type == "number":
            n = float(canonical)
            return f"{int(n):,}" if n.is_integer() else f"{n:,}"
        return str(canonical)
    return str(value)


def fields_view(specs: list[FieldSpec] | None, values: dict[str, Any], edited: set[str]) -> list[dict[str, Any]]:
    """Every field in the type's order, then any value the type does not declare in the order it was set. A case
    with no type lists its values in the order they were set, as text."""
    declared = specs or []
    out: list[dict[str, Any]] = []
    for s in declared:
        out.append(_one(s, values.get(s.key), s.key in edited, declared=True))
    known = {s.key for s in declared}
    for key, value in values.items():
        if key not in known:
            out.append(_one(FieldSpec(key, key, "text"), value, key in edited, declared=False))
    return out


def _one(spec: FieldSpec, value: Any, edited: bool, *, declared: bool) -> dict[str, Any]:
    return {
        "key": spec.key,
        "label": spec.label,
        "type": spec.type,
        "display": display(spec, value),
        "raw": value,
        "fileId": value if spec.type == "file" and isinstance(value, str) and value else None,
        "required": spec.required,
        "declared": declared,
        "edited": edited,
    }
