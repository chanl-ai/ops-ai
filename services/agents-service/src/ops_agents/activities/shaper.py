"""Tool results as widget parts (c-055 spec, "Widget architecture"): a shape and its data, never a tool or component
name; the console picks how to draw each shape.

    {type: "widget", id, shape: rows | series | record | metric, data, hint?}

Pure: no database, no network. `shape_part` returns None when nothing fits, and the result stays a plain tool card.

Rules, in order:
- An operation's declared shape (`x-ops-shape` on its response, `declared`) wins when the data fits that shape;
  when it does not, inference runs as if nothing were declared. A malformed part is never emitted.
- An object whose only key holds a list (`{"transactions": [...]}`) is read as that list; the key becomes the title.
- A value that is not flat is drawn as one cell (c-055 T024): a list of scalars joins with ", " (`accountIds`), a
  list of objects or a nested object becomes a count naming its key ("2 holds", "1 address"), so a customer with
  accounts or an account with holds still draws. Inference reads the flat columns only; a joined or counted cell is
  text, never a number or a date.
- rows: a non-empty list of objects. At most MAX_ROWS rows are kept, and the hint's `truncatedFrom` says how many
  there were.
- series: rows where every key but one is numeric in every row, and that one key (the x axis) is a date (ISO
  `YYYY-MM-DD` at the start) in every row, or an ordinal: integers strictly increasing down the rows. At least two
  rows. A row with any other text key stays rows, so no column is dropped; the person can still chart it.
- metric: an object with a numeric `value` and a text `label`, and nothing else but an optional text `unit` and a
  numeric `delta`.
- record: any other non-empty object.
"""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any, cast

SHAPES = ("rows", "series", "record", "metric")
MAX_ROWS = 200
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _flat(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _singular(key: str) -> str:
    """`holds` -> `hold`, `addresses` -> `address`; a key already singular (`address`, `status`) stays as it is."""
    if key.endswith(("sses", "xes", "zes", "ches", "shes")):
        return key[:-2]
    if key.endswith("s") and not key.endswith("ss") and len(key) > 1:
        return key[:-1]
    return key


def _cell(key: str, value: Any) -> Any:
    """`value` as one cell: flat as it is; a list of scalars joined; a list of objects or a nested object as a count
    naming its key, so the column says what it holds without unfolding it."""
    if _flat(value):
        return value
    if isinstance(value, list):
        items = cast(list[Any], value)
        if all(_flat(v) for v in items):
            return ", ".join("" if v is None else str(v) for v in items)
        n = len(items)
        return f"{n} {_singular(key) if n == 1 else key}"
    if isinstance(value, dict):
        n = len(cast(dict[str, Any], value))
        return f"1 {_singular(key)}" if n else f"0 {key}"
    return str(value)


def _flatten(row: dict[str, Any]) -> dict[str, Any]:
    return {k: _cell(k, v) for k, v in row.items()}


def _rows(data: Any) -> list[dict[str, Any]] | None:
    if not isinstance(data, list) or not data:
        return None
    rows: list[dict[str, Any]] = []
    for r in cast(list[Any], data):
        if not isinstance(r, dict):
            return None
        row = cast(dict[str, Any], r)
        if not row:
            return None
        rows.append(_flatten(row))
    return rows[:MAX_ROWS]


def _series(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], str] | None:
    if len(rows) < 2:
        return None
    keys = list(rows[0])
    if any(list(r) != keys for r in rows):
        return None
    numeric = [k for k in keys if all(_number(r[k]) for r in rows)]
    others = [k for k in keys if k not in numeric]
    if len(others) == 1:
        x = others[0]
        if not all(isinstance(r[x], str) and DATE.match(r[x]) for r in rows):
            return None
    elif not others and numeric:
        # Every column numeric: the first is the x axis when it is an ordinal (integers strictly increasing).
        x = keys[0]
        values = [r[x] for r in rows]
        if not all(isinstance(v, int) for v in values) or any(b <= a for a, b in pairwise(values)):
            return None
        numeric = [k for k in numeric if k != x]
    else:
        return None
    if not numeric:
        return None
    data = {"x": [r[x] for r in rows], "series": [{"name": k, "y": [r[k] for r in rows]} for k in numeric]}
    return data, x


def _metric(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    d = cast(dict[str, Any], data)
    if not (_number(d.get("value")) and isinstance(d.get("label"), str)):
        return None
    if set(d) - {"value", "label", "unit", "delta"}:
        return None
    if "unit" in d and not isinstance(d["unit"], str):
        return None
    if "delta" in d and not _number(d["delta"]):
        return None
    return d


def _record(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict) or not data:
        return None
    return _flatten(cast(dict[str, Any], data))


def _as(shape: str, data: Any) -> tuple[Any, dict[str, Any]] | None:
    """`data` as `shape`, with its hint, or None when it does not fit."""
    if shape == "rows":
        rows = _rows(data)
        if rows is None:
            return None
        return rows, ({"truncatedFrom": len(cast(list[Any], data))} if len(cast(list[Any], data)) > len(rows) else {})
    if shape == "series":
        rows = _rows(data)
        found = _series(rows) if rows is not None else None
        return (found[0], {"x": found[1]}) if found else None
    if shape == "metric":
        metric = _metric(data)
        return (metric, {}) if metric is not None else None
    if shape == "record":
        record = _record(data)
        return (record, {}) if record is not None and _metric(data) is None else None
    return None


def shape_part(output: Any, *, part_id: str, declared: str | None = None) -> dict[str, Any] | None:
    """The widget part for a tool's `output`, or None when it stays a plain tool card."""
    data: Any = output
    title: str | None = None
    if isinstance(output, dict) and len(cast(dict[str, Any], output)) == 1:
        ((key, value),) = cast(dict[str, Any], output).items()
        if isinstance(value, list):
            data, title = cast(list[Any], value), key
    order = ([declared] if declared in SHAPES else []) + ["series", "rows", "metric", "record"]
    for shape in order:
        found = _as(shape, data)
        if found is None:
            continue
        payload, hint = found
        if title:
            hint = {**hint, "title": title}
        part: dict[str, Any] = {"type": "widget", "id": part_id, "shape": shape, "data": payload}
        if hint:
            part["hint"] = hint
        return part
    return None
