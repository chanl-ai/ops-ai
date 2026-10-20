"""The extract step's scoring (c-157), by failure mode: an invented quote accepted; a quote on another page accepted; a
money or date value in another format rejected, or a wrong one accepted; an OCR'd field scored as if read cleanly; a
missing required field passing; a step threshold below the workspace floor skipping review."""

from __future__ import annotations

from typing import Any

from ops_contracts.field_values import normalise
from ops_extract.checks import answer_schema, ground, score

PAGES = {1: "Invoice INV-2219\nDate: 17 October 2026", 2: "Amount due: $1,234.50\nDue 30 Nov 2026"}
INVOICE: dict[str, Any] = {"key": "invoice_no", "type": "text", "required": True}
AMOUNT: dict[str, Any] = {"key": "amount", "type": "money", "required": True}
DUE: dict[str, Any] = {"key": "due_date", "type": "date", "required": True}


def scored(
    field: dict[str, object],
    answer: dict[str, object] | None,
    *,
    ocr: set[int] | None = None,
    below: float | None = None,
    floor: float = 0.8,
) -> dict[str, Any]:
    return score(field, answer, PAGES, ocr or set(), file_id="fil_1", schema_below=below, floor=floor)


def test_an_invented_or_misplaced_quote_scores_zero_and_goes_to_review() -> None:
    invented = scored(INVOICE, {"value": "INV-9999", "quote": "Invoice INV-9999", "page": 1})
    elsewhere = scored(INVOICE, {"value": "INV-2219", "quote": "Invoice INV-2219", "page": 2})
    found = scored(INVOICE, {"value": "INV-2219", "quote": "Invoice INV-2219", "page": 1})
    assert invented["confidence"] == 0 and invented["needsReview"]
    assert elsewhere["confidence"] == 0 and elsewhere["needsReview"]
    assert found["confidence"] == 1.0 and not found["needsReview"]
    assert found["citation"] == {"fileId": "fil_1", "page": 1, "quote": "Invoice INV-2219"}


def test_a_quote_found_only_after_folding_counts_for_less() -> None:
    assert ground("invoice   inv-2219", 1, PAGES) == 0.85
    assert ground("Invoice INV-2219", 1, PAGES) == 1.0


def test_money_and_dates_in_other_formats_are_normalised_and_bad_ones_rejected() -> None:
    assert normalise(AMOUNT, "$1,234.50") == (1234.5, 0.9)
    assert normalise(AMOUNT, 1234.5) == (1234.5, 1.0)
    assert normalise(AMOUNT, "1.234,50 €") == (1234.5, 0.9)
    assert normalise(AMOUNT, "twelve") == (None, 0.0)
    assert normalise(DUE, "30 Nov 2026") == ("2026-11-30", 0.9)
    assert normalise(DUE, "2026-11-30") == ("2026-11-30", 1.0)
    assert normalise(DUE, "31 Nov 2026") == (None, 0.0)
    bad = scored(DUE, {"value": "someday", "quote": "Due 30 Nov 2026", "page": 2})
    assert bad["confidence"] == 0 and bad["needsReview"]


def test_an_ocr_page_scores_down() -> None:
    clean = scored(AMOUNT, {"value": "$1,234.50", "quote": "$1,234.50", "page": 2})
    ocr = scored(AMOUNT, {"value": "$1,234.50", "quote": "$1,234.50", "page": 2}, ocr={2})
    assert clean["confidence"] == 0.9 and ocr["confidence"] == 0.63 and ocr["needsReview"]


def test_a_missing_required_field_cannot_pass_and_nothing_found_carries_no_confidence() -> None:
    """An empty optional field showed 100% confidence on the file page (c-262)."""
    missing = scored(DUE, {"value": None, "quote": None, "page": None})
    optional = scored({**DUE, "required": False}, None)
    assert missing["confidence"] is None and missing["needsReview"] and missing["citation"] is None
    assert optional["confidence"] is None and not optional["needsReview"]


def test_review_uses_the_highest_threshold_so_a_step_cannot_go_below_the_floor() -> None:
    answer: dict[str, Any] = {"value": "$1,234.50", "quote": "$1,234.50", "page": 2}  # scores 0.9
    assert scored({**AMOUNT, "reviewBelow": 0.1}, answer, floor=0.95)["needsReview"], (
        "a field threshold below the floor"
    )
    assert scored(AMOUNT, answer, below=0.1, floor=0.95)["needsReview"], "a schema threshold below the floor"
    assert scored({**AMOUNT, "reviewBelow": 0.95}, answer, floor=0.5)["needsReview"], (
        "a field threshold above the floor"
    )
    assert not scored(AMOUNT, answer, floor=0.8)["needsReview"]
    assert scored({**AMOUNT, "alwaysReview": True}, answer, floor=0.0)["needsReview"], "always reviewed"


def test_the_answer_schema_asks_value_quote_and_page_per_field() -> None:
    s = answer_schema([INVOICE, AMOUNT])
    assert s["required"] == ["invoice_no", "amount"]
    assert s["properties"]["amount"]["required"] == ["value", "quote", "page"]


def test_a_real_quote_with_an_invented_value_scores_zero() -> None:
    invented_amount = scored(AMOUNT, {"value": "$9,999.00", "quote": "$1,234.50", "page": 2})
    invented_date = scored(DUE, {"value": "2026-12-01", "quote": "Due 30 Nov 2026", "page": 2})
    invented_text = scored(INVOICE, {"value": "INV-0001", "quote": "Invoice INV-2219", "page": 1})
    true_date = scored(DUE, {"value": "30 Nov 2026", "quote": "Due 30 Nov 2026", "page": 2})
    assert invented_amount["confidence"] == 0 and invented_date["confidence"] == 0 and invented_text["confidence"] == 0
    assert true_date["confidence"] == 0.9 and true_date["value"] == "2026-11-30"


def test_a_numeric_date_reads_in_the_types_order() -> None:
    """03/04/2026 is March 4 on a US levy and 3 April on a day-first document (levy demo, c-270)."""
    pages = {1: "Due 03/04/2026"}
    answer: dict[str, Any] = {"value": "03/04/2026", "quote": "Due 03/04/2026", "page": 1}
    us = score({**DUE, "dateOrder": "MDY"}, answer, pages, set(), file_id="fil_1", schema_below=None, floor=0.8)
    day_first = score({**DUE, "dateOrder": "DMY"}, answer, pages, set(), file_id="fil_1", schema_below=None, floor=0.8)
    assert (us["value"], day_first["value"]) == ("2026-03-04", "2026-04-03"), (us, day_first)
    assert us["confidence"] > 0 and day_first["confidence"] > 0, "the quote backs the value in either order"
    # A field with no order (an Extract from file step with its own fields) reads as a document type with none does.
    unset = score(DUE, answer, pages, set(), file_id="fil_1", schema_below=None, floor=0.8)
    assert unset["value"] == us["value"], unset


CLEAN_PAGES = {
    1: "Judgment debtor QUINN CAPTION, of Albany\nSSN XXX-XX-3301\nCase reference: SYN-TL-2026-0101\nAt 10:30 am"
}


def clean_score(field: dict[str, Any], value: str, quote: str) -> dict[str, Any]:
    return score(field, {"value": value, "quote": quote, "page": 1}, CLEAN_PAGES, set(), **CLEAN_FLOOR)


CLEAN_FLOOR: dict[str, Any] = {"file_id": "fil_1", "schema_below": None, "floor": 0.8}


def test_cleanup_rules_save_the_value_without_what_the_model_copied_around_it() -> None:
    """c-287: a trailing comma, a masked number given whole and a kept label are cleaned before scoring; what the model
    said stays as extractedValue, and the cleaned value is still backed by the quote."""
    name = clean_score({"key": "n", "type": "text", "clean": ["trimPunctuation"]}, "QUINN CAPTION,", "QUINN CAPTION,")
    last4 = clean_score(
        {"key": "s", "type": "text", "clean": ["lastFour"], "pattern": r"\d{4}"}, "XXX-XX-3301", "SSN XXX-XX-3301"
    )
    case = clean_score(
        {"key": "c", "type": "text", "clean": ["stripLabel"]},
        "Case reference: SYN-TL-2026-0101",
        "Case reference: SYN-TL-2026-0101",
    )
    assert (name["value"], last4["value"], case["value"]) == ("QUINN CAPTION", "3301", "SYN-TL-2026-0101")
    assert name["extractedValue"] == "QUINN CAPTION," and name["cleaned"] == ["trimPunctuation"], name
    assert all(r["confidence"] == 1.0 and not r["needsReview"] for r in (name, last4, case)), (name, last4, case)


def test_a_field_without_cleanup_rules_or_a_value_they_do_not_fit_is_left_as_said() -> None:
    plain = clean_score({"key": "n", "type": "text"}, "QUINN CAPTION,", "QUINN CAPTION,")
    time_of_day = clean_score({"key": "t", "type": "text", "clean": ["stripLabel"]}, "10:30 am", "At 10:30 am")
    short = clean_score({"key": "s", "type": "text", "clean": ["lastFour"]}, "330", "SSN XXX-XX-3301")
    assert (plain["value"], time_of_day["value"], short["value"]) == ("QUINN CAPTION,", "10:30 am", "330")
    assert "cleaned" not in plain and "cleaned" not in time_of_day, (plain, time_of_day)
