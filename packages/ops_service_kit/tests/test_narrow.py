"""The narrowing helpers' outcomes on input that is not the shape a caller hoped for."""

import pytest

from ops_service_kit import narrow
from ops_service_kit.http import JsonList, JsonValue


@pytest.mark.parametrize("value", [None, "text", 3, ["a"], True])
def test_a_value_that_is_not_an_object_reads_as_an_empty_one(value: object) -> None:
    assert narrow.json_object(value) == {}
    held = {"a": 1}
    assert narrow.json_object(held) is held


def test_a_value_that_is_not_json_is_refused() -> None:
    with pytest.raises(ValueError):
        narrow.as_json({"when": object()})
    assert narrow.as_json({"a": [1, "b", None]}) == {"a": [1, "b", None]}


def test_field_of_the_wrong_kind_reads_as_the_default() -> None:
    obj = {"name": 7, "count": True, "label": "x"}
    assert narrow.field(obj, "name", str) is None
    assert narrow.field(obj, "name", str, "") == ""
    assert narrow.field(obj, "count", int, 0) == 0
    assert narrow.field(obj, "missing", str, "none") == "none"
    assert narrow.field(obj, "label", str) == "x"
    assert narrow.field({"rate": 3}, "rate", float) == 3.0


def test_a_value_that_decides_something_fails_on_a_wrong_shape() -> None:
    with pytest.raises(narrow.Malformed, match="counts is not an object"):
        narrow.an_object("junk", "counts")
    with pytest.raises(narrow.Malformed, match="rows is not a list"):
        narrow.a_list({}, "rows")
    for bad in ({"published": "2"}, {"published": True}, {"published": None}, {}):
        with pytest.raises(narrow.Malformed, match="published is not a int"):
            narrow.required(bad, "published", int)
    assert narrow.required({"published": 2}, "published", int) == 2


def test_entries_iterates_as_value_or_empty_did_and_refuses_what_cannot_iterate() -> None:
    held: JsonList = ["a", "b"]
    assert narrow.entries(held) is held
    assert narrow.entries({"k": 1, "j": 2}) == ["k", "j"]
    assert narrow.entries("ab") == ["a", "b"]
    falsy_values: tuple[JsonValue, ...] = (None, "", 0, False, [], {})
    for falsy in falsy_values:
        assert narrow.entries(falsy) == []
    for scalar in (3, 2.5, True):
        with pytest.raises(narrow.Malformed):
            narrow.entries(scalar)
