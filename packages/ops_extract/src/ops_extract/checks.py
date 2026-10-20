"""Extracted-field checks (c-157, c-235): a field's confidence comes from signals these checks verify, never from the
model. The quote the model gives must be on the page it cites; the value must be a valid value of its type; a page
read by OCR counts for less. A field needs a person when its confidence is below the highest of its own threshold, the
schema's and the workspace floor, or when it is always reviewed, so no step can set a threshold below the floor.

Pure functions only: the caller (files-service's extraction API, the engine's Extract from file step) parses the file
and calls the model, then hands the answers here.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, cast

import regex

# The value types and their canonical forms are shared with case types (ops_contracts.field_values).
from ops_contracts.field_values import DEFAULT_DATE_ORDER, as_date, as_number, normalise

# Signals (research, c-157): quote exact 1.0, found after folding 0.85, not found 0; value valid as given 1.0,
# normalised 0.9, invalid 0; a page read by OCR multiplies by its words' recognition confidence when the reader kept
# it (a layout, c-247), else by 0.7.
EXACT, FOLDED = 1.0, 0.85
OCR_FACTOR = 0.7
# The longest a field's `pattern` may take on one value (c-247).
PATTERN_SECONDS = 0.05
DEFAULT_FLOOR = 0.8

_SPACE = re.compile(r"\s+")
_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"})

# A field's cleanup rules (`clean`, c-287), run on the model's text before the field's other rules and its score, for
# copying habits a description does not stop: a trailing comma after a name, a masked number given whole, a label kept
# with its value. Each is opt-in per field, so a value that needs its punctuation keeps it.
# The rule a rejected value broke, on the field's result as `rejected` (c-247, c-296).
REJECTED_TYPE = "type"
TRIM_PUNCTUATION = "trimPunctuation"
LAST_FOUR = "lastFour"
STRIP_LABEL = "stripLabel"
CLEAN_RULES = (TRIM_PUNCTUATION, LAST_FOUR, STRIP_LABEL)
_TRAILING = re.compile(r"[\s,;:]+$")
# A label is a short run of words starting with a letter, then a colon and space: "Case reference: ", "Release: ".
_LABEL = re.compile(r"^[A-Za-z][A-Za-z .#/()'-]{0,39}:\s+(?=\S)")


def fold(text: str) -> str:
    """Text compared loosely: Unicode-normalised, curly quotes and dashes made plain, case and runs of space ignored."""
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", text).translate(_QUOTES)).strip().casefold()


def ground(quote: str | None, page: int | None, pages: dict[int, str]) -> float:
    """How well a quote is found on the page it cites: exactly, after folding, or not at all (0, so an invented quote
    is never accepted, whatever the value)."""
    if not quote or not quote.strip() or page is None or page not in pages:
        return 0.0
    text = pages[page]
    if quote in text:
        return EXACT
    return FOLDED if fold(quote) in fold(text) else 0.0


def in_quote(field: dict[str, Any], value: Any, quote: str | None) -> bool:
    """Whether the value is what the quote says, so a true quote cannot carry an invented value: a number or money
    amount is one of the quote's numbers, a date is one of its dates, text and enum values appear in it."""
    if not quote or value is None:
        return False
    kind = str(field.get("type") or "text")
    if kind in ("number", "money"):
        numbers = [as_number(m)[0] for m in re.findall(r"-?[\d][\d.,\s]*\d|\d", quote)]
        return any(n is not None and abs(n - float(value)) < 0.005 for n in numbers)
    if kind == "date":
        order = str(field.get("dateOrder") or DEFAULT_DATE_ORDER)
        return str(value) in {d for d in (as_date(m, order)[0] for m in _date_candidates(quote)) if d}
    return fold(str(value)) in fold(quote)


def _date_candidates(text: str) -> list[str]:
    """Substrings of `text` that may be a date: ISO, numeric with / . -, or with a month name."""
    patterns = (
        r"\d{4}-\d{2}-\d{2}",
        r"\d{4}/\d{1,2}/\d{1,2}",
        r"\d{1,2}[/.-]\d{1,2}[/.-]\d{4}",
        r"\d{1,2} [A-Za-z]{3,9} \d{4}",
        r"[A-Za-z]{3,9} \d{1,2}, \d{4}",
    )
    return [m for p in patterns for m in re.findall(p, text)]


def threshold(field: dict[str, Any], schema_below: float | None, floor: float) -> float:
    """The confidence a field must reach: the highest of its own, the schema's and the workspace floor."""
    return max(float(field.get("reviewBelow") or 0), float(schema_below or 0), floor)


def quote_confidence(quote: str | None, words: dict[str, float] | None) -> float:
    """An OCR'd quote's confidence: the mean of its words' recognition confidence, or OCR_FACTOR when the reader kept
    none for this page or none of the quote's words were recognised alone."""
    if not quote or not words:
        return OCR_FACTOR
    found = [words[w] for w in fold(quote).split() if w in words]
    return sum(found) / len(found) if found else OCR_FACTOR


def cleaned(field: dict[str, Any], raw: Any) -> tuple[Any, list[str]]:
    """The model's value after the field's cleanup rules, in the order the field lists them, and the rules that changed
    it. Anything but text is left as it is; so is a last four when the value has fewer than four digits."""
    if not isinstance(raw, str):
        return raw, []
    text, changed = raw, list[str]()
    for rule in cast(list[str], field.get("clean") or []):
        before = text
        if rule == TRIM_PUNCTUATION:
            text = _TRAILING.sub("", text)
        elif rule == STRIP_LABEL:
            text = _LABEL.sub("", text.strip())
        elif rule == LAST_FOUR:
            digits = re.sub(r"\D", "", text)
            text = digits[-4:] if len(digits) >= 4 else text
        if text != before:
            changed.append(rule)
    return text, changed


def broken_rule(field: dict[str, Any], raw: Any) -> str | None:
    """Which of the field's own rules the model's value breaks (c-247): `emptyWhen`, phrases that mean the document
    gives no value ("Not supplied on this form"), or `pattern`, a regular expression the whole value must match (a
    full SSN, so a masked "***-**-4321" is not one). None when it keeps both."""
    text = str(raw).strip()
    for phrase in cast(list[str], field.get("emptyWhen") or []):
        if fold(text) == fold(phrase) or fold(text).startswith(fold(phrase)):
            return "emptyWhen"
    pattern = field.get("pattern")
    if isinstance(pattern, str) and pattern:
        # A team writes the pattern and the model writes the text, so a pattern that backtracks badly could hold the
        # extraction for minutes on `re`; `regex` gives up after PATTERN_SECONDS, and a value that cannot be checked
        # in time is treated as not matching.
        try:
            if regex.fullmatch(pattern, text, timeout=PATTERN_SECONDS) is None:
                return "pattern"
        except TimeoutError:
            return "pattern"
    return None


def score(
    field: dict[str, Any],
    answer: dict[str, Any] | None,
    pages: dict[int, str],
    ocr_pages: set[int],
    *,
    file_id: str,
    schema_below: float | None,
    floor: float,
    word_confidence: dict[int, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """One field's result: the normalised value, what the model said, the confidence from the signals, whether a person
    must check it, and where it came from."""
    said_value = (answer or {}).get("value")
    raw, tidied = cleaned(field, said_value)
    quote = (answer or {}).get("quote")
    page = (answer or {}).get("page")
    page = int(page) if isinstance(page, int | float) and not isinstance(page, bool) else None
    missing = raw is None or (isinstance(raw, str) and not raw.strip())
    rule = None if missing else broken_rule(field, raw)
    if rule is not None:
        # The value breaks a rule the document type sets: kept as what the model said, never used, and marked, so a
        # person sees why the field is empty (a masked SSN offered as the full number, a placeholder as an address).
        return {
            "value": None,
            "extractedValue": said_value,
            "confidence": 0.0,
            "needsReview": True,
            "rejected": rule,
            "citation": {"fileId": file_id, "page": page, "quote": quote},
        }
    if missing:
        # Nothing found carries no confidence: a required field goes to a person, an optional one has nothing to check.
        return {
            "value": None,
            "extractedValue": None,
            "confidence": None,
            "needsReview": bool(field.get("required")) or bool(field.get("alwaysReview")),
            "citation": None,
        }
    value, valid = normalise(field, raw)
    said = str(quote) if quote is not None else None
    # The quote must be on its page and must say the value: either failing means nothing backs the value.
    confidence = ground(said, page, pages) * valid * (1.0 if in_quote(field, value, said) else 0.0)
    if page in ocr_pages:
        confidence *= quote_confidence(said, (word_confidence or {}).get(page))
    confidence = round(confidence, 3)
    review = bool(field.get("alwaysReview")) or confidence < threshold(field, schema_below, floor)
    result: dict[str, Any] = {
        "value": value,
        "extractedValue": said_value,
        "confidence": confidence,
        "needsReview": review,
        "citation": {"fileId": file_id, "page": page, "quote": quote},
    }
    if tidied:
        result["cleaned"] = tidied
    if value is None:
        # Said, but not a valid value of the field's type (a date of 41/18/2026): named, so a re-read is asked why.
        result["rejected"] = REJECTED_TYPE
    return result


def answer_schema(fields: list[dict[str, Any]]) -> dict[str, Any]:
    """The JSON Schema the model answers: per field its value as written, the exact quote it came from and the page."""
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": ["value", "quote", "page"],
        "properties": {
            "value": {"type": ["string", "number", "null"]},
            "quote": {"type": ["string", "null"]},
            "page": {"type": ["integer", "null"]},
        },
    }
    keys = [str(f["key"]) for f in fields]
    return {"type": "object", "additionalProperties": False, "required": keys, "properties": dict.fromkeys(keys, item)}


def records_schema(fields: list[dict[str, Any]]) -> dict[str, Any]:
    """The answer for a document that names several of the thing (Extract many): one `answer_schema` object per
    record, in the order the document gives them."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["records"],
        "properties": {"records": {"type": "array", "items": answer_schema(fields)}},
    }
