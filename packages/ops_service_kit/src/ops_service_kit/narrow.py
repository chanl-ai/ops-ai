"""Typed reads of untyped input (a parsed body, a stored JSON column, another service's answer), in place of
`cast(dict[str, Any], x)`. A cast checks nothing; these check the shape and fall back to an empty or default value,
so a caller writes the fallback once instead of `x if isinstance(x, dict) else {}` at every read."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast, overload

from pydantic import TypeAdapter

from .http import Json, JsonList, JsonValue

_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


def json_object(value: object) -> Json:
    """`value` itself when it is an object (so a write through the result reaches the original), else a new empty
    object. Never raises. The keys and values are trusted to be JSON, as from `json.loads` or a JSON column."""
    return cast(Json, value) if isinstance(value, dict) else {}


def json_list(value: object) -> JsonList:
    """`value` itself when it is a list, else a new empty list. Never raises."""
    return cast(JsonList, value) if isinstance(value, list) else []


def as_json(value: object) -> JsonValue:
    """`value` checked to be JSON all the way down, for input whose origin is not a JSON parser. A value that is not
    JSON (an object, a set, a non-string key) raises ValueError."""
    return _JSON.validate_python(value)


@overload
def field[T: (str, int, float, bool)](obj: Mapping[str, JsonValue], key: str, kind: type[T]) -> T | None: ...
@overload
def field[T: (str, int, float, bool)](obj: Mapping[str, JsonValue], key: str, kind: type[T], default: T) -> T: ...
def field[T: (str, int, float, bool)](
    obj: Mapping[str, JsonValue], key: str, kind: type[T], default: T | None = None
) -> T | None:
    """The scalar at `key` when it is a `kind`, else `default`. A boolean is not read as a number: JSON keeps them
    apart, and `isinstance(True, int)` would not. A whole number reads as a float when a float is asked for, as JSON
    has one number type. For an object or a list use `json_object(obj.get(key))`."""
    value = obj.get(key)
    if isinstance(value, bool) and kind is not bool:
        return default
    if kind is float and isinstance(value, int):
        return kind(value)
    return value if isinstance(value, kind) else default
