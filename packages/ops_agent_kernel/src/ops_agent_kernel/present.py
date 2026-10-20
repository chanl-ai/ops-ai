"""The built-in `present` tool (c-055 T021): the model's way to return a shaped answer, a comparison table as rows or
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
NAME = "present"
SERVER = "kernel"

PRESENT = ToolGrant(
    NAME,
    SERVER,
    "Show the person a shaped result from facts already in this conversation: a table (rows: a list of flat objects "
    "with the same keys), a chart (series: rows with one date or ordinal key and numeric values), one record (record: "
    "a flat object) or one figure (metric: {label, value, unit?, delta?}). Or give kind, a generic widget the same in "
    "any industry, with data in that kind's fields (* required): " + kinds.describe() + ". Use it for comparisons and "
    "summaries; it reads nothing and changes nothing.",
    "read",
    {
        "type": "object",
        "properties": {
            "shape": {"type": "string", "enum": list(SHAPES)},
            "kind": {"type": "string", "enum": list(kinds.KINDS)},
            "data": {"description": "The rows, record or metric to show, in the shape's form."},
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
        "required": ["data"],
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
    """This turn's present tool (c-082): the four shapes always; `widget` when the agent has widgets, its enum the
    agent's list and one use-when line per widget in the description (the implicit skill); `layout` when the agent may
    compose. An agent with neither gets today's tool unchanged."""
    if not settings.widgets and not settings.compose:
        return PRESENT
    schema: dict[str, Any] = {k: v for k, v in PRESENT.input_schema.items() if k != "required"}
    props: dict[str, Any] = dict(schema["properties"])
    props["data"] = {
        "description": "For shape, the rows, record or metric. For widget, an object with that widget's fields."
    }
    desc = PRESENT.description.replace(
        "Use it for comparisons", "Give exactly one of shape, kind, widget or layout. Use it for comparisons"
    )
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


def _ungranted(part: dict[str, Any], granted: set[str]) -> list[str]:
    return [t for t in layout.required_tools(part.get("layout")) if t not in granted]


def run(
    arguments: dict[str, Any], settings: AgentSettings, granted: set[str] | None = None
) -> tuple[dict[str, Any] | None, str]:
    """The part this call shows and what the model is told, or (None, the refusal). Exactly one form is used: a shape,
    one of the agent's widgets filled with data, or a composed layout when the agent may compose. A button whose
    `requires` names a tool this turn was not granted refuses the part, so a widget never offers an action the agent
    cannot take (`granted` None skips the check)."""
    shape, widget, tree = arguments.get("shape"), arguments.get("widget"), arguments.get("layout")
    kind = arguments.get("kind")
    forms = [f for f in (shape, kind, widget, tree) if f is not None]
    if len(forms) != 1:
        return None, "Give exactly one of shape, kind, widget or layout."
    data = arguments.get("data")
    if kind is not None:
        if kind not in kinds.SCHEMAS:
            return None, f"kind must be one of {', '.join(kinds.KINDS)}."
        schema = kinds.SCHEMAS[str(kind)]
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
