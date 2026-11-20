"""How a start's values are read by their declared types, one case per rule written in
docs/architecture/workflow-runner.md ("Run input"): what text becomes a number, a whole number or true/false, what is
refused, and what counts as a required field left empty."""

from __future__ import annotations

from typing import Any, cast

import pytest

from ops_engine.starts import InputRefusedError, run_input, typed_values

TYPES: dict[str, Any] = {
    "type": "object",
    "properties": {
        "n": {"type": "number", "title": "Amount"},
        "i": {"type": "integer", "title": "Count"},
        "b": {"type": "boolean", "title": "Urgent"},
        "s": {"type": "string", "title": "Postcode"},
    },
}
REFUSED = object()


@pytest.mark.parametrize(
    ("field", "sent", "stored"),
    [
        ("n", " 12 ", 12),  # spaces around a number are a form's or a cell's, not part of it
        ("n", "12.50", 12.5),
        ("n", "-0.5", -0.5),
        ("n", "1e3", REFUSED),  # plain decimals only: no exponent
        ("n", "1,200", REFUSED),
        ("n", "\u0661\u0662", REFUSED),  # digits other than 0-9
        ("n", "9" * 41, REFUSED),  # longer than any number a person sends
        ("n", "nan", REFUSED),
        ("n", float("inf"), REFUSED),  # JSON 1e999: no database column stores it
        ("n", float("nan"), REFUSED),
        ("i", "12", 12),
        ("i", "12.0", 12),  # a whole number written with a zero fraction, as text
        ("i", 12.0, 12),  # and as JSON: stored the same way
        ("i", "12.5", REFUSED),
        ("i", 12.5, REFUSED),
        ("b", "TRUE", True),
        ("b", " false ", False),
        ("b", "yes", REFUSED),
        ("b", 1, REFUSED),
        ("s", "01234", "01234"),
        ("s", 1234, REFUSED),  # a number is never turned into text
        ("n", True, REFUSED),
    ],
)
def test_text_is_read_as_its_declared_type_by_one_written_rule(field: str, sent: Any, stored: Any) -> None:
    if stored is REFUSED:
        with pytest.raises(InputRefusedError) as refused:
            typed_values(TYPES, {field: sent})
        assert (refused.value.field, refused.value.code) == (field, "invalid_input")
        return
    got = typed_values(TYPES, {field: sent})[field]
    assert got == stored and type(got) is type(stored), got


@pytest.mark.parametrize("empty", [None, "", "  ", [], {}])
def test_a_required_field_sent_empty_is_refused(empty: Any) -> None:
    schema: dict[str, Any] = {"type": "object", "required": ["s"], "properties": {"s": {"title": "Postcode"}}}
    with pytest.raises(InputRefusedError) as refused:
        typed_values(schema, {"s": empty})
    assert refused.value.field == "s" and refused.value.missing == ("Postcode",)


def test_a_number_that_is_not_finite_is_refused_wherever_it_sits_and_without_a_schema() -> None:
    nested: dict[str, Any] = {"type": "object", "properties": {"rows": {"type": "array"}}}
    with pytest.raises(InputRefusedError) as refused:
        typed_values(nested, {"rows": [{"amount": float("-inf")}]})
    assert (refused.value.field, refused.value.code) == ("rows", "invalid_input")
    with pytest.raises(InputRefusedError) as refused:
        run_input(None, {"amount": float("inf")}, cast(Any, None))  # a trigger that declares no input schema
    assert refused.value.field == "amount"
