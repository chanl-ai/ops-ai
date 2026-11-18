"""How a JSON document stored in a column is read as a named shape, without changing what is stored.

  OPERATION_COPY = stored(OperationCopy)          # a TypedDict
  copy = OPERATION_COPY(row.baseline)             # typed view, the same keys and values in the same order
  full = OPERATION_COPY(row.baseline, defaults=operation_defaults())   # keys an old row lacks, filled

Validating stored JSON into a model drops or rejects keys that old rows must keep, and a cast checks nothing. A reader
checks the value against the shape and returns a shallow copy of the stored mapping: keys the shape does not declare
are kept, a missing optional key stays missing, and the order is the stored order, so a caller that writes the document
back writes what was stored plus its own change. The check is pydantic's strict JSON mode, the types the column can
hold: an `int` key holding "4" fails, while an enum, `datetime` or `Decimal` key passes on the string it is stored as
(the view still holds that string). The copy is shallow: a nested list or object is the stored one.
"""

from __future__ import annotations

import copy
import json
from functools import cache
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

if TYPE_CHECKING:
    from _typeshed import SupportsItems


class StoredShapeError(ValueError):
    """A stored document is not a JSON object, or a key the shape declares holds another type."""


@cache
def _adapter(shape: type) -> TypeAdapter[object]:
    return TypeAdapter(shape)


def _key(loc: tuple[int | str, ...]) -> str:
    # The top-level key: deeper parts name a union member or a nested position, which the caller reads off the cause.
    return str(loc[0]) if loc else "(document)"


class Reader[S]:
    """A reader of stored documents of one shape, a TypedDict; its adapter is built once per shape."""

    def __init__(self, shape: type[S]) -> None:
        if issubclass(shape, BaseModel):
            # A model would read as a dict cast to the model, and one that forbids extras refuses kept keys.
            raise TypeError(f"stored() reads a TypedDict, not the model {shape.__name__}; validate a model directly")
        self.shape = shape

    def __call__(self, value: object, *, defaults: SupportsItems[str, object] | None = None) -> S:
        """`value` as `S`. With `defaults`, a key the document lacks is added after the stored keys, from a copy of
        the default, so neither the stored value nor the defaults are changed. Raises `StoredShapeError` naming the
        shape and the key when the value is not an object or a declared key holds another type."""
        name = self.shape.__name__
        if not isinstance(value, dict):
            raise StoredShapeError(f"{name}: a stored document is a JSON object, not {type(value).__name__}")
        document = cast("dict[str, JsonValue]", value).copy()
        if defaults is not None:
            for key, default in defaults.items():
                if key not in document:
                    document[key] = cast("JsonValue", copy.deepcopy(default))
        try:
            _adapter(self.shape).validate_json(json.dumps(document), strict=True)
        except TypeError as e:
            raise StoredShapeError(f"{name}: the document holds a value JSON cannot store") from e
        except ValidationError as e:
            keys = ", ".join(sorted({_key(err["loc"]) for err in e.errors()}))
            raise StoredShapeError(f"{name}: {keys} does not match the declared type") from e
        return cast("S", document)


def stored[S](shape: type[S]) -> Reader[S]:
    """The reader of stored documents shaped as `shape`."""
    return Reader(shape)
