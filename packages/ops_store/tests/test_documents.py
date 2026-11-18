"""A stored JSON document read as a named shape, by failure mode: a key the shape does not declare is dropped; the
read changes the order or a value; a default is written into the stored value or filled unasked; a wrong type or a
non-object passes."""

from __future__ import annotations

import json
from typing import NotRequired, TypedDict

import pytest

from ops_store.documents import StoredShapeError, stored


class Field(TypedDict):
    name: str
    size: int
    hint: NotRequired[str | None]


FIELD = stored(Field)


def test_unknown_keys_survive_a_read() -> None:
    value = {"name": "amount", "size": 4, "legacy": {"x": 1}}
    assert FIELD(value) == value


def test_read_then_dump_is_byte_identical() -> None:
    raw = '{"size": 4, "zeta": [1, "2"], "name": "amount", "hint": null, "alpha": 1.50}'
    assert json.dumps(FIELD(json.loads(raw))) == json.dumps(json.loads(raw))


def test_missing_optional_key_stays_missing_unless_defaults_are_asked_for() -> None:
    value = {"name": "amount", "size": 4}
    assert "hint" not in FIELD(value)
    filled = FIELD(value, defaults={"hint": "none", "name": "ignored"})
    assert list(filled.items()) == [("name", "amount"), ("size", 4), ("hint", "none")]
    assert value == {"name": "amount", "size": 4}


def test_wrong_type_on_a_declared_key_names_the_shape_and_key() -> None:
    with pytest.raises(StoredShapeError, match=r"Field: size "):
        FIELD({"name": "amount", "size": "4"})


def test_a_non_object_is_refused() -> None:
    with pytest.raises(StoredShapeError, match="Field: a stored document is a JSON object, not list"):
        FIELD([{"name": "amount", "size": 4}])
