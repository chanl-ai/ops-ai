"""Tool results as widget parts ("Widget architecture"): a shape and its data, never a tool or component
name; the console picks how to draw each shape.

    {type: "widget", id, shape: rows | series | record | metric, data, hint?}

Pure: no database, no network. `shape_part` returns None when nothing fits, and the result stays a plain tool card.

Rules, in order:
- An operation's declared shape (`x-ops-shape`, `declared`) wins when the data fits it; otherwise inference runs.
- One list in an envelope is read as that list (`_listed`): an object's only key, or its only list of objects beside a
  count, a done flag or a paging link (`{totalSize, done, records}`). Other text beside a list keeps a record.
- A cell that is not flat is one cell: a list of scalars joined with ", ", a list of objects or a nested object a
  count naming its key ("2 holds"). Inference reads the flat columns only.
- rows: a non-empty list of objects, at most MAX_ROWS (the hint's `truncatedFrom` says how many there were). A key
  holding an object in every row is per-row metadata, not a column; its common `type` titles the table ("Accounts").
- series: rows whose keys are all numeric but one, a date or an increasing integer (the x axis); two rows at least.
- metric: a numeric `value` and a text `label`, with only an optional text `unit` and numeric `delta` beside them.
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


def _object_columns(rows: list[dict[str, Any]]) -> set[str]:
    """Keys holding an object in every row: per-row metadata such as Salesforce's `attributes`, which a table would
    draw as "1 attribute" in each row."""
    keys = set(rows[0]) if rows else set[str]()
    return {k for k in keys if all(isinstance(r.get(k), dict) for r in rows)}


def _rows(data: Any) -> list[dict[str, Any]] | None:
    if not isinstance(data, list) or not data:
        return None
    raw: list[dict[str, Any]] = []
    for r in cast(list[Any], data):
        if not isinstance(r, dict):
            return None
        row = cast(dict[str, Any], r)
        if not row:
            return None
        raw.append(row)
    dropped = _object_columns(raw)
    rows = [_flatten({k: v for k, v in r.items() if k not in dropped}) for r in raw]
    if any(not r for r in rows):
        return None
    return rows[:MAX_ROWS]


# A list's key that names nothing about its rows: an envelope's generic container.
CONTAINER_KEYS = {"records", "items", "data", "results", "result", "rows", "entries", "list", "value", "values"}


def _plural(word: str) -> str:
    if word.endswith("y") and len(word) > 1 and word[-2].lower() not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "ch", "sh")):
        return word + "es"
    return word + "s"


def _kind_of(rows: Any) -> str | None:
    """The rows' own type, when every row's metadata object names the same one (`attributes.type` in Salesforce's
    records): "Account" titles the table "Accounts"."""
    if not isinstance(rows, list) or not rows:
        return None
    raw = [cast(dict[str, Any], r) for r in cast(list[Any], rows) if isinstance(r, dict)]
    types: set[str] = set()
    for k in _object_columns(raw):
        found = {str(cast(dict[str, Any], r[k]).get("type") or "") for r in raw}
        if len(found) == 1 and (t := found.pop()):
            types.add(t)
    return _plural(types.pop()) if len(types) == 1 else None


def _title(key: str | None, rows: Any, fallback: str | None) -> str | None:
    """A table's title: its rows' own type, else the list's key when it names them (`transactions`), else the tool's
    title, never a generic container key such as `records`."""
    if (kind := _kind_of(rows)) is not None:
        return kind
    if key and key.lower() not in CONTAINER_KEYS:
        return key
    return fallback


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


def _objects(items: list[Any]) -> bool:
    return bool(items) and all(isinstance(r, dict) for r in items)


# An envelope's own keys beside its list: a next-page link, cursor or token. Any other text beside a list (a customer's
# id beside their addresses) makes the object a record.
PAGING_KEY = re.compile(r"next|cursor|token|page|url|link", re.IGNORECASE)


def _paging(key: str, value: Any) -> bool:
    """Whether a value beside a list is the envelope's own: a count, a done flag, null, or a paging link."""
    if value is None or isinstance(value, bool | int | float):
        return True
    return isinstance(value, str) and bool(PAGING_KEY.search(key))


def _listed(output: Any) -> tuple[str, list[Any]] | None:
    """(key, list) when `output` is one list in an envelope: its only key, or its only list of objects beside a count,
    a done flag or a next-page link (Salesforce's {totalSize, done, nextRecordsUrl, records})."""
    if not isinstance(output, dict):
        return None
    o = cast(dict[str, Any], output)
    if len(o) == 1:
        ((key, value),) = o.items()
        return (key, cast(list[Any], value)) if isinstance(value, list) else None
    lists = [k for k, v in o.items() if isinstance(v, list) and _objects(cast(list[Any], v))]
    if len(lists) == 1 and all(_paging(k, v) for k, v in o.items() if k != lists[0]):
        return lists[0], cast(list[Any], o[lists[0]])
    return None


def shape_part(
    output: Any, *, part_id: str, declared: str | None = None, title: str | None = None
) -> dict[str, Any] | None:
    """The widget part for a tool's `output`, or None when it stays a plain tool card. `title` is the tool's own (a
    plugin tool's), which a table falls back to when its rows and key name nothing."""
    data: Any = output
    key: str | None = None
    found = _listed(output)
    if found is not None:
        key, data = found
    title = _title(key, data, title) if found is not None else _kind_of(data)
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
