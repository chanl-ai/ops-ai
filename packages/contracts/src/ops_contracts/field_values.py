"""Field value types: the types a document type's field and a case type's field may have, and each type's canonical
form. A value is read in its type's form and scored by how much it had to change: as given (1.0), reformatted (0.9:
a date to ISO, a money string to a number, an enum's case), or not a valid value (None, 0). Extraction scores fields
with it (ops_extract.checks); a case shows and checks its fields with it (agents-service case_fields), without
importing extraction.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

FIELD_TYPES = ("text", "number", "money", "date", "enum")
VALID, NORMALISED = 1.0, 0.9
_NAMED_FORMATS = ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%Y/%m/%d")
# A numeric date's order is the document type's setting (`dateOrder`): 03/04/2026 is March 4 in a US levy and 3 April
# in a day-first one. A field with no setting reads month first, as a document type with none does.
DATE_ORDERS = ("MDY", "DMY")
DEFAULT_DATE_ORDER = "MDY"
_NUMERIC_FORMATS = {
    "MDY": ("%m/%d/%Y", "%m.%d.%Y", "%m-%d-%Y"),
    "DMY": ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y"),
}
_CURRENCY = re.compile(r"[A-Za-z$€£¥]+")


def as_number(raw: Any) -> tuple[float | None, float]:
    if isinstance(raw, bool):
        return None, 0.0
    if isinstance(raw, int | float):
        return float(raw), VALID
    if not isinstance(raw, str):
        return None, 0.0
    s = _CURRENCY.sub("", raw).replace(" ", "").replace("\u00a0", "")
    # 1.234,56: the comma is the decimal point.
    s = s.replace(".", "").replace(",", ".") if re.fullmatch(r"-?\d{1,3}(\.\d{3})+,\d+", s) else s.replace(",", "")
    try:
        return float(Decimal(s)), (VALID if s == raw.strip() else NORMALISED)
    except InvalidOperation:
        return None, 0.0


def as_date(raw: Any, order: str = DEFAULT_DATE_ORDER) -> tuple[str | None, float]:
    if not isinstance(raw, str) or not raw.strip():
        return None, 0.0
    s = raw.strip()
    try:
        return date.fromisoformat(s).isoformat(), VALID
    except ValueError:
        pass
    for fmt in (*_NAMED_FORMATS, *_NUMERIC_FORMATS.get(order, _NUMERIC_FORMATS[DEFAULT_DATE_ORDER])):
        try:
            return datetime.strptime(s, fmt).date().isoformat(), NORMALISED
        except ValueError:
            continue
    return None, 0.0


def normalise(field: dict[str, Any], raw: Any) -> tuple[Any, float]:
    """The value in its type's canonical form and how much it was changed to get there: as given (1.0), reformatted
    (0.9: a date to ISO, a money string to a number, an enum's case), or not a valid value at all (None, 0)."""
    kind = str(field.get("type") or "text")
    if kind in ("number", "money"):
        value, signal = as_number(raw)
        if value is not None and kind == "money":
            value = round(value, 2)
        return value, signal
    if kind == "date":
        return as_date(raw, str(field.get("dateOrder") or DEFAULT_DATE_ORDER))
    if kind == "enum":
        options = [str(o) for o in cast(list[Any], field.get("options") or [])]
        if isinstance(raw, str) and raw in options:
            return raw, VALID
        matched = next((o for o in options if isinstance(raw, str) and o.casefold() == raw.strip().casefold()), None)
        return (matched, NORMALISED) if matched is not None else (None, 0.0)
    if isinstance(raw, str | int | float) and not isinstance(raw, bool) and str(raw).strip():
        return str(raw).strip(), VALID
    return None, 0.0
