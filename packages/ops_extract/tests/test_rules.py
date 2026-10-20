"""Checks across fields (c-296), by failure mode: a total that does not add up or a due date before the issue date
passing (F1); a check failing because the document does not print a field it names (F2); a value of the wrong type
not named, so its re-read is not told why (F3); a check naming a field the version lacks, or of no known kind (F5)."""

from __future__ import annotations

from typing import Any

from ops_extract.checks import score
from ops_extract.rules import apply, failed, problems

SUM = {"id": "total_adds_up", "kind": "sum", "fields": ["subtotal", "tax"], "equals": "total"}
ORDER = {"id": "due_after_issue", "kind": "before", "earlier": "issued", "later": "due"}


def read(**values: Any) -> dict[str, dict[str, Any]]:
    return {k: {"value": v, "extractedValue": v, "needsReview": False} for k, v in values.items()}


def test_a_total_that_does_not_add_up_and_a_due_date_first_send_their_fields_to_review() -> None:
    fields = read(subtotal=100.0, tax=13.0, total=118.0, issued="2026-10-20", due="2026-10-01")
    apply(fields, [SUM, ORDER])
    assert all(
        fields[k]["needsReview"] and fields[k]["rejected"] == "check:total_adds_up"
        for k in ("subtotal", "tax", "total")
    )
    assert fields["due"]["rejected"] == "check:due_after_issue" and set(failed(fields)) == set(fields)


def test_checks_that_hold_or_lack_a_field_leave_the_read_alone() -> None:
    holds = read(subtotal=100.0, tax=13.0, total=113.004, issued="2026-10-01", due="2026-10-31")
    lacking = read(subtotal=100.0, tax=None, total=118.0)
    apply(holds, [SUM, ORDER])
    apply(lacking, [SUM])
    assert failed(holds) == {} and failed(lacking) == {}


def test_a_value_of_the_wrong_type_is_named_so_its_re_read_is_told_why() -> None:
    field = {"key": "due", "type": "date"}
    got = score(field, {"value": "41/18/2026", "quote": "41/18/2026", "page": 1}, {1: "Due 41/18/2026"}, set(),
                file_id="f", schema_below=None, floor=0.8)  # fmt: skip
    assert got["value"] is None and got["rejected"] == "type"
    assert failed({"due": got}) == {"due": ("41/18/2026", "is not a valid value of its type")}


def test_a_check_naming_another_field_or_of_no_known_kind_is_refused() -> None:
    keys = {"subtotal", "tax", "total"}
    assert problems([SUM], keys) == []
    assert problems([{**SUM, "equals": "grand_total"}], keys) == [
        "check total_adds_up names 'grand_total', not fields of the version"
    ]
    assert problems([{"id": "x", "kind": "ratio"}], keys) == ["check x: kind is one of sum, before"]


def test_a_check_over_a_field_of_the_wrong_type_is_refused_at_save_and_never_fails_a_read() -> None:
    """A sum naming a text field raised on float() and failed the whole read (F6); a before naming a number compared
    strings. The version is refused when saved; a read saved before that skips the check instead of failing."""
    types = {"subtotal": "money", "tax": "text", "total": "money", "issued": "date", "due": "number"}
    found = problems([SUM, ORDER], set(types), types)
    assert any("'tax' must be number or money" in p for p in found), found
    assert any("'due' must be date" in p for p in found), found
    fields = read(subtotal=100.0, tax="thirteen", total=118.0)
    apply(fields, [SUM])
    assert not failed(fields), fields
