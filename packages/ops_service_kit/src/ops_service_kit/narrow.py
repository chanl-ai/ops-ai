"""Typed reads of untyped input (a parsed body, a stored JSON column, another service's answer), in place of
`cast(dict[str, Any], x)`. A cast checks nothing; these check the shape and fall back to an empty or default value,
so a caller writes the fallback once instead of `x if isinstance(x, dict) else {}` at every read.

The falling-back reads (`json_object`, `json_list`, `field`) suit display and optional data. A value that decides
something (a guard, a count, a billed amount, what is saved) is read with `an_object`, `a_list` or `required`, which
raise `Malformed` on a wrong shape, so bad input fails the call instead of reading as empty or zero."""

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


class Malformed(ValueError):
    """Input that had to have a shape did not have it."""


def an_object(value: object, what: str) -> Json:
    """`value` itself when it is an object, else `Malformed` naming `what`."""
    if not isinstance(value, dict):
        raise Malformed(f"{what} is not an object")
    return cast(Json, value)


def a_list(value: object, what: str) -> JsonList:
    """`value` itself when it is a list, else `Malformed` naming `what`."""
    if not isinstance(value, list):
        raise Malformed(f"{what} is not a list")
    return cast(JsonList, value)


def required[T: (str, int, float, bool)](obj: Mapping[str, JsonValue], key: str, kind: type[T]) -> T:
    """The scalar at `key`, read as `field` reads it, or `Malformed` when it is missing or another type."""
    value = field(obj, key, kind)
    if value is None:
        raise Malformed(f"{key} is not a {kind.__name__}")
    return value


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
