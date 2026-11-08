"""The built-in `present` tool: the model's way to return a shaped answer, a comparison table as rows or
a figure as a metric, without a tool result behind it. The turn records the call like any other and puts a widget part
on it (`ToolCallRecord.view["part"]`), which the chat stream emits as a part; nothing leaves the process.

The shape and the data are checked here, so a malformed part is never emitted: the model gets the refusal back as a
tool error and can try again.
"""

from __future__ import annotations

from typing import Any, cast

from . import kinds, layout
from .types import AgentSettings, ToolGrant

SHAPES = ("rows", "series", "record", "metric")
# The quick replies under a reply (ChatMessage.follow_ups): a few short answers, never a menu.
MAX_FOLLOW_UPS = 3
FOLLOW_UP_CHARS = 120


def follow_ups(arguments: dict[str, Any]) -> tuple[list[str] | None, str | None]:
    """The call's quick replies, or why they are refused; (None, None) when it gives none."""
    raw = arguments.get("followUps")
    if raw is None:
        return None, None
    if not isinstance(raw, list) or not raw or len(cast(list[Any], raw)) > MAX_FOLLOW_UPS:
        return None, f"followUps is a list of one to {MAX_FOLLOW_UPS} short replies."
    replies = [str(r).strip() for r in cast(list[Any], raw)]
    if any(not r or len(r) > FOLLOW_UP_CHARS for r in replies):
        return None, f"Each follow-up is a reply of 1 to {FOLLOW_UP_CHARS} characters."
    return list(dict.fromkeys(replies)), None


NAME = "present"
SERVER = "kernel"

PRESENT = ToolGrant(
    NAME,
    SERVER,
    "Show the person a table, chart, record or figure built from facts already in this conversation; it reads "
    "nothing and changes nothing. A tool's own result is already shown to the person, so do not present it again; "
    "use this for comparisons and summaries you put together. Pass data and at most one of: shape (rows: a list of "
    "flat objects with the same keys; series: rows with one date or ordinal key and numeric values; record: one flat "
    "object; metric: {label, value, unit?, delta?}) or kind, a generic widget with data in its fields (* required; "
    "columns may be plain key names): " + kinds.describe() + ". With data alone, a list shows as a table and an "
    "object as a record.",
    "read",
    {
        "type": "object",
        "properties": {
            "shape": {"type": "string", "enum": list(SHAPES)},
            "kind": {"type": "string", "enum": list(kinds.KINDS)},
            "data": {"description": "The rows, record or metric to show, in the shape's form."},
            "followUps": {
                "type": "array",
                "maxItems": MAX_FOLLOW_UPS,
                "items": {"type": "string", "maxLength": FOLLOW_UP_CHARS},
                "description": "Up to three short replies the person is likely to send next, such as the answers to "
                "a question you ask; shown as chips that send the reply. May be given alone, with no data.",
            },
            "hint": {
                "type": "object",
                "description": "Optional: title, x (the series key), y (the value keys), prefer (table, line, bar, "
                "area).",
                "properties": {
                    "title": {"type": "string"},
                    "x": {"type": "string"},
                    "y": {"type": "array", "items": {"type": "string"}},
                    "prefer": {"type": "string"},
                },
            },
        },
    },
)


def _flat(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def check(shape: str, data: Any) -> str | None:
    """Why `data` is not a valid `shape`, or None when it is."""
    if shape not in SHAPES:
        return f"shape must be one of {', '.join(SHAPES)}."
    if shape in ("rows", "series"):
        if not isinstance(data, list) or not data:
            return f"{shape} data must be a non-empty list of objects."
        rows = cast(list[Any], data)
        if not all(isinstance(r, dict) and all(_flat(v) for v in cast(dict[str, Any], r).values()) for r in rows):
            return f"{shape} data must be objects whose values are text, numbers, booleans or null."
        if shape == "series" and len(rows) < 2:
            return "series data needs at least two rows."
        return None
    if not isinstance(data, dict) or not data:
        return f"{shape} data must be a non-empty object."
    record = cast(dict[str, Any], data)
    if not all(_flat(v) for v in record.values()):
        return f"{shape} data must have values that are text, numbers, booleans or null."
    if shape == "metric" and ("label" not in record or not isinstance(record.get("value"), int | float)):
        return "metric data needs a text label and a numeric value."
    return None


def part(shape: str, data: Any, hint: dict[str, Any] | None) -> dict[str, Any]:
    """The widget part the chat emits for this call; its id is set by the chat from the call's id."""
    out: dict[str, Any] = {"type": "widget", "id": "", "shape": shape, "data": data}
    clean = {k: v for k, v in (hint or {}).items() if k in ("title", "x", "y", "prefer") and v is not None}
    if clean:
        out["hint"] = clean
    return out


_COMPOSE_LINE = (
    " Or give layout: a tree of card, row, column, text, title, caption, badge, metric, table, chart, keyValue, list, "
    "button and divider nodes with literal values, each {type, ...fields, children?}."
)
_BUTTON_LINE = (
    " A button's reply text is sent back to you as the person's next message; it does nothing else. Show each thing"
    " once: do not present the same widget again for a reply to it, and do not repeat a widget's contents in your text."
)
_NODE: dict[str, Any] = {
    "type": "object",
    "required": ["type"],
    "properties": {
        "type": {"enum": [k for k in layout.CATALOGUE if k != "image"]},
        "children": {"type": "array", "items": {"$ref": "#/$defs/node"}},
        "title": {"type": "string"},
        "text": {"type": "string"},
        "label": {"type": "string"},
        "value": {},
        "unit": {"type": "string"},
        "delta": {"type": "number"},
        "tone": {"type": "string", "enum": list(layout.TONES)},
        "rows": {"type": "array", "items": {"type": "object"}},
        "columns": {"type": "array", "items": {"type": "object"}},
        "items": {"type": "array"},
        "x": {"type": "string"},
        "y": {"type": "array", "items": {"type": "string"}},
        "kind": {"type": "string", "enum": list(layout.CHARTS)},
        "gap": {"type": "string", "enum": list(layout.GAPS)},
        "align": {"type": "string", "enum": list(layout.ALIGNS)},
        "reply": {"type": "object", "properties": {"text": {"type": "string"}, "values": {"type": "object"}}},
        "requires": {"type": "string", "description": "A button's tool: one this agent holds."},
    },
}


def grant(settings: AgentSettings) -> ToolGrant:
    """This turn's present tool: the four shapes always; `widget` when the agent has widgets, its enum the
    agent's list and one use-when line per widget in the description (the implicit skill); `layout` when the agent may
    compose. An agent with neither gets today's tool unchanged."""
    if not settings.widgets and not settings.compose:
        return PRESENT
    schema: dict[str, Any] = {k: v for k, v in PRESENT.input_schema.items() if k != "required"}
    props: dict[str, Any] = dict(schema["properties"])
    props["data"] = {
        "description": "For shape, the rows, record or metric. For widget, an object with that widget's fields."
    }
    desc = PRESENT.description.replace("at most one of: shape", "at most one of: widget, layout, shape")
    if settings.widgets:
        props["widget"] = {"type": "string", "enum": [w.widget_id for w in settings.widgets]}
        desc += " Or give widget with data matching its fields. Widgets: " + " ".join(
            f"{w.widget_id}: {w.use_when.strip()}" for w in settings.widgets
        )
    if settings.compose:
        props["layout"] = {"$ref": "#/$defs/node"}
        schema["$defs"] = {"node": _NODE}
        desc += _COMPOSE_LINE
    schema["properties"] = props
    return ToolGrant(NAME, SERVER, desc + _BUTTON_LINE, "read", schema)


def _rows_of(part: dict[str, Any]) -> list[dict[str, Any]]:
    data = part.get("data")
    if part.get("shape") == "rows" and isinstance(data, list):
        return [cast(dict[str, Any], r) for r in cast(list[Any], data) if isinstance(r, dict)]
    if part.get("shape") == "record" and isinstance(data, dict):
        return [cast(dict[str, Any], data)]
    return []


def already_shown(part: dict[str, Any], shown: list[dict[str, Any]]) -> bool:
    """Whether every row of a presented table or record is one a tool's result already drew this turn, field for
    field (a presented row may leave fields out). A chart, a metric, a widget or a layout is never a repeat."""
    rows = _rows_of(part)
    drawn = [r for p in shown for r in _rows_of(p)]
    if not rows or not drawn:
        return False

    def within(row: dict[str, Any]) -> bool:
        return any(all(str(d.get(k)) == str(v) for k, v in row.items()) for d in drawn)

    return all(within(r) for r in rows)


def _ungranted(part: dict[str, Any], granted: set[str]) -> list[str]:
    return [t for t in layout.required_tools(part.get("layout")) if t not in granted]


def _columns(value: Any) -> Any:
    """A table's columns as the catalogue keeps them: a plain key name is the column {key}."""
    if not isinstance(value, list):
        return value
    return [{"key": c} if isinstance(c, str) else c for c in cast(list[Any], value)]


def _plain(arguments: dict[str, Any]) -> dict[str, Any]:
    """A call as a model most often writes it, read as it meant: data alone is a table (a list) or a record (an
    object), and a table's columns may be plain key names, in a kind's data or in a composed layout's table nodes."""
    out = dict(arguments)
    if all(out.get(k) is None for k in ("shape", "kind", "widget", "layout")) and out.get("data") is not None:
        data = out["data"]
        out["shape"] = "rows" if isinstance(data, list) else "record" if isinstance(data, dict) else None
    if out.get("kind") == "table" and isinstance(out.get("data"), dict):
        data = dict(cast(dict[str, Any], out["data"]))
        if "columns" in data:
            data["columns"] = _columns(data["columns"])
        out["data"] = data
    if isinstance(out.get("layout"), dict):
        out["layout"] = _layout_columns(out["layout"])
    return out


def _layout_columns(node: Any) -> Any:
    if not isinstance(node, dict):
        return node
    n = dict(cast(dict[str, Any], node))
    if n.get("type") == "table" and "columns" in n:
        n["columns"] = _columns(n["columns"])
    if isinstance(n.get("children"), list):
        n["children"] = [_layout_columns(c) for c in cast(list[Any], n["children"])]
    return n


def _changed_only(data: Any) -> Any:
    """An entity's fields without those reported as changed to the value they already had: a field with `was` equal to
    `value` is not a change, so a saved card shows only what the save changed."""
    unchanged: Any = data
    record = cast(dict[str, Any], data) if isinstance(data, dict) else None
    given = record.get("fields") if record is not None else None
    if record is None or not isinstance(given, list):
        return unchanged
    fields: list[Any] = []
    for raw in cast(list[Any], given):
        f = cast(dict[str, Any], raw) if isinstance(raw, dict) else None
        if f is not None and "was" in f and str(f["was"]) == str(f.get("value")):
            continue
        fields.append(raw)
    return {**record, "fields": fields}


def run(
    arguments: dict[str, Any], settings: AgentSettings, granted: set[str] | None = None
) -> tuple[dict[str, Any] | None, str]:
    """The part this call shows and what the model is told, or (None, the refusal). Exactly one form is used: a shape,
    one of the agent's widgets filled with data, or a composed layout when the agent may compose. A button whose
    `requires` names a tool this turn was not granted refuses the part, so a widget never offers an action the agent
    cannot take (`granted` None skips the check)."""
    arguments = _plain(arguments)
    shape, widget, tree = arguments.get("shape"), arguments.get("widget"), arguments.get("layout")
    kind = arguments.get("kind")
    forms = [f for f in (shape, kind, widget, tree) if f is not None]
    if len(forms) > 1:
        return None, "Pass data with only one of shape, kind, widget or layout."
    if not forms:
        return None, "Pass data: a list of objects shows as a table, an object as a record."
    data = arguments.get("data")
    if kind is not None:
        if kind not in kinds.SCHEMAS:
            return None, f"kind must be one of {', '.join(kinds.KINDS)}."
        schema = kinds.SCHEMAS[str(kind)]
        if kind == "entity":
            data = _changed_only(data)
        try:
            filled = layout.fill(kinds.template(str(kind)), schema, data)
        except layout.LayoutError as e:
            return None, f"{e} The {kind} kind's fields are: {layout.fields_of(schema)}."
        part_ = {"type": "widget", "id": "", "kind": kind, "layout": filled}
        if granted is not None and (missing := _ungranted(part_, granted)):
            return None, f"A button requires {', '.join(missing)}, which this agent does not have; drop the button."
        return part_, str(kind)
    if shape is not None:
        raw_hint = arguments.get("hint")
        hint: dict[str, Any] | None = dict(cast(dict[str, Any], raw_hint)) if isinstance(raw_hint, dict) else None
        why = check(str(shape), data)
        return (None, why) if why else (part(str(shape), data, hint), str(shape))
    if widget is not None:
        w = next((t for t in settings.widgets if t.widget_id == widget), None)
        if w is None:
            names = ", ".join(t.widget_id for t in settings.widgets) or "none"
            return None, f"{widget!r} is not one of this agent's widgets ({names})."
        try:
            filled = layout.fill(w.tree, w.schema, data)
        except layout.LayoutError as e:
            return None, f"{e} The {w.widget_id} widget's fields are: {layout.fields_of(w.schema)}."
        ref = {"id": w.widget_id, "version": w.version, "name": w.name}
        part_ = {"type": "widget", "id": "", "template": ref, "layout": filled}
        if granted is not None and (missing := _ungranted(part_, granted)):
            return None, f"The {w.widget_id} widget needs {', '.join(missing)}, which this agent does not have."
        return part_, w.widget_id
    if not settings.compose:
        return None, "This agent may not compose layouts; use a shape or one of its widgets."
    try:
        composed = layout.check(tree)
    except layout.LayoutError as e:
        return None, str(e)
    part_ = {"type": "widget", "id": "", "layout": composed}
    if granted is not None and (missing := _ungranted(part_, granted)):
        return None, f"A button requires {', '.join(missing)}, which this agent does not have; drop the button."
    return part_, "layout"
