# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Checks across a read's fields (c-296), declared on the document type version beside its fields, from a fixed set
of kinds so a type carries them as configuration:

    {"id": "total_adds_up", "kind": "sum", "fields": ["subtotal", "tax"], "equals": "total", "tolerance": 0.01}
    {"id": "due_after_issue", "kind": "before", "earlier": "invoice_date", "later": "due_date"}

A check runs only when every field it names has a value, so a document that does not print a part is not failed for
it. A failing check sends the fields it names to review with `rejected: "check:<id>"`, and every field a rule rejected
is what the one targeted re-read asks again."""

from __future__ import annotations

from typing import Any, cast

from ops_extract.checks import REJECTED_TYPE

SUM = "sum"
BEFORE = "before"
CHECK_KINDS = (SUM, BEFORE)
CHECK_PREFIX = "check:"
DEFAULT_TOLERANCE = 0.01
# Why each rule failed, in the words a re-read is told.
REASONS = {
    REJECTED_TYPE: "is not a valid value of its type",
    "pattern": "does not match the field's pattern",
    "emptyWhen": "is a placeholder the document prints instead of a value",
}


def named(check: dict[str, Any]) -> list[str]:
    """The fields a check reads."""
    if check.get("kind") == SUM:
        return [*cast(list[str], check.get("fields") or []), str(check.get("equals") or "")]
    return [str(check.get("earlier") or ""), str(check.get("later") or "")]


# The field types each kind of check reads: a sum adds numbers, a before compares dates.
READS = {SUM: ("number", "money"), BEFORE: ("date",)}


def problems(checks: Any, keys: set[str], types: dict[str, str] | None = None) -> list[str]:
    """What is wrong with a version's checks, refused when it is saved: an id each, a known kind, only fields of the
    version, and (with the fields' `types`) fields of a type the kind reads."""
    if not isinstance(checks, list):
        return ["checks is a list"]
    found: list[str] = []
    for c in cast(list[Any], checks):
        check = cast(dict[str, Any], c) if isinstance(c, dict) else {}
        cid = str(check.get("id") or "")
        if not cid:
            found.append("every check has an id")
        elif check.get("kind") not in CHECK_KINDS:
            found.append(f"check {cid}: kind is one of {', '.join(CHECK_KINDS)}")
        elif missing := [k for k in named(check) if k not in keys]:
            found.append(f"check {cid} names {', '.join(repr(m) for m in missing)}, not fields of the version")
        elif types is not None and (
            wrong := [k for k in named(check) if types.get(k, "text") not in READS[check["kind"]]]
        ):
            takes = " or ".join(READS[check["kind"]])
            found.append(
                f"check {cid}: {', '.join(repr(w) for w in wrong)} must be {takes} fields for a {check['kind']}"
            )
    return found


def _fails(check: dict[str, Any], values: dict[str, Any]) -> bool | None:
    """True when the check fails, False when it holds, None when a field it names has no value."""
    maybe = [values.get(k) for k in named(check)]
    if any(v is None for v in maybe):
        return None
    got = cast(list[Any], maybe)
    if check["kind"] == SUM:
        try:
            parts, total = [float(v) for v in got[:-1]], float(got[-1])
        except (TypeError, ValueError):
            return None  # a value that is not a number cannot be added; its own type check names it
        return abs(sum(parts) - total) > float(check.get("tolerance") or DEFAULT_TOLERANCE)
    return str(got[0]) > str(got[1])  # ISO dates compare in order


def apply(fields: dict[str, dict[str, Any]], checks: list[dict[str, Any]]) -> None:
    """Marks the fields each failing check names: sent to review, with the check named unless a rule already was."""
    values = {k: r.get("value") for k, r in fields.items()}
    for check in checks:
        if _fails(check, values):
            for key in named(check):
                if key in fields:
                    fields[key]["needsReview"] = True
                    fields[key].setdefault("rejected", f"{CHECK_PREFIX}{check['id']}")


def failed(fields: dict[str, dict[str, Any]]) -> dict[str, tuple[Any, str]]:
    """Each field a rule rejected, with what was read and why it failed, as a re-read is told."""
    out: dict[str, tuple[Any, str]] = {}
    for key, r in fields.items():
        rule = r.get("rejected")
        if not rule:
            continue
        reason = REASONS.get(str(rule)) or f"breaks the check {str(rule).removeprefix(CHECK_PREFIX)}"
        out[key] = (r.get("extractedValue"), reason)
    return out
