"""Widget layouts (c-082, `docs/architecture/chat-widgets.md`): a tree of catalogue primitives the console draws
in chat, either composed by the model or filled from a builder's published widget template.

Nothing outside the catalogue can be emitted. Every tree is rebuilt here from closed per-primitive field lists before a
part leaves the kernel, so the console only receives primitives it already draws: no HTML, no script, no event handler,
no link, and an image only as its blocked placeholder. A button carries the text it sends back to the agent as the
person's next message, which is the only thing a widget can do. A template binds data with `{"$bind": "/pointer"}`
(JSON Pointer); there is no expression language, so a template is data and never code.
"""

from __future__ import annotations

from typing import Any, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from . import kinds

# Size limits on one tree (checks L3 and L6): a layout a person can read in a chat bubble, and a bound on what one tool
# call can make the console draw.
MAX_NODES = 200
MAX_DEPTH = 6
MAX_CHILDREN = 50
MAX_TEXT = 2000
MAX_TOTAL_TEXT = 16_000
MAX_ROWS = 50
MAX_COLUMNS = 20
MAX_BUTTONS = 10

TONES = ("neutral", "info", "success", "warning", "danger")
CHARTS = ("line", "bar", "area")
FORMATS = ("text", "number", "money", "date", "percent")
GAPS = ("sm", "md", "lg")
ALIGNS = ("start", "center", "end", "between")

# Each primitive: its fields (name -> kind), whether it holds children, and the fields it needs.
CATALOGUE: dict[str, tuple[dict[str, str], bool, tuple[str, ...]]] = {
    "card": ({"title": "text"}, True, ()),
    "row": ({"gap": "gap", "align": "align"}, True, ()),
    "column": ({"gap": "gap", "align": "align"}, True, ()),
    "title": ({"text": "text"}, False, ("text",)),
    "text": ({"text": "text"}, False, ("text",)),
    "caption": ({"text": "text"}, False, ("text",)),
    "badge": ({"text": "text", "tone": "tone", "tones": "tones"}, False, ("text",)),
    "metric": (
        {
            "label": "text",
            "value": "cell",
            "unit": "text",
            "delta": "number",
            "deltaLabel": "text",
            "goodWhen": "direction",
            "trend": "numbers",
        },
        False,
        ("label", "value"),
    ),
    "table": ({"rows": "rows", "columns": "columns"}, False, ("rows",)),
    "chart": ({"rows": "rows", "x": "text", "y": "keys", "kind": "chart"}, False, ("rows", "x", "y")),
    "keyValue": ({"items": "pairs"}, False, ("items",)),
    "list": ({"items": "items"}, False, ("items",)),
    # `requires` names the tool the click asks the agent to use; the agent must hold it (checked on pin and per turn).
    "button": ({"label": "text", "reply": "reply", "requires": "text"}, False, ("label", "reply")),
    "divider": ({}, False, ()),
    "image": ({"alt": "text", "src": "text"}, False, ("alt",)),
    # The c-176 kinds: each checked whole against its JSON Schema (`kinds.SCHEMAS`), which closes every object in it.
    **{
        k: (dict.fromkeys(kinds.SCHEMAS[k]["properties"], "kind"), False, tuple(kinds.SCHEMAS[k]["required"]))
        for k in kinds.KINDS
        if k not in kinds.PRIMITIVES
    },
}


class LayoutError(ValueError):
    """Why a layout or a template's data was refused; the model gets the message back as a tool error."""


def _flat(v: Any) -> bool:
    return v is None or isinstance(v, str | int | float | bool)


class _Walk:
    """One check of one tree: counts nodes, text and buttons, and rebuilds each node from its closed fields."""

    def __init__(self, *, images: bool, prune: bool = False) -> None:
        self.prune = prune
        self.nodes = 0
        self.text = 0
        self.buttons = 0
        self.images = images

    def text_of(self, v: Any, where: str) -> str:
        if not isinstance(v, str):
            raise LayoutError(f"{where}: must be text.")
        if len(v) > MAX_TEXT:
            raise LayoutError(f"{where}: longer than {MAX_TEXT} characters.")
        self.text += len(v)
        if self.text > MAX_TOTAL_TEXT:
            raise LayoutError(f"{where}: the layout holds more than {MAX_TOTAL_TEXT} characters of text.")
        return v

    def cell(self, v: Any, where: str) -> Any:
        if not _flat(v):
            raise LayoutError(f"{where}: must be text, a number, a boolean or null.")
        return self.text_of(v, where) if isinstance(v, str) else v

    def field(self, kind: str, v: Any, where: str) -> Any:
        if kind == "text":
            return self.text_of(v, where)
        if kind == "cell":
            return self.cell(v, where)
        if kind == "number":
            if isinstance(v, bool) or not isinstance(v, int | float):
                raise LayoutError(f"{where}: must be a number.")
            return v
        choices = {"tone": TONES, "chart": CHARTS, "gap": GAPS, "align": ALIGNS, "direction": ("up", "down")}.get(kind)
        if choices is not None:
            if v not in choices:
                raise LayoutError(f"{where}: must be one of {', '.join(choices)}.")
            return v
        if kind == "tones":
            if not isinstance(v, dict) or len(cast(dict[str, Any], v)) > MAX_COLUMNS:
                raise LayoutError(f"{where}: must map at most {MAX_COLUMNS} values to tones.")
            return {
                self.text_of(k, where): self.field("tone", t, f"{where}/{k}")
                for k, t in cast(dict[str, Any], v).items()
            }
        if kind == "numbers":
            if not isinstance(v, list) or not 2 <= len(cast(list[Any], v)) <= 60:
                raise LayoutError(f"{where}: must list 2 to 60 numbers.")
            return [self.field("number", x, f"{where}/{i}") for i, x in enumerate(cast(list[Any], v))]
        if kind == "keys":
            if not isinstance(v, list) or not 0 < len(cast(list[Any], v)) <= MAX_COLUMNS:
                raise LayoutError(f"{where}: must list 1 to {MAX_COLUMNS} keys.")
            return [self.text_of(k, f"{where}/{i}") for i, k in enumerate(cast(list[Any], v))]
        if kind == "items":
            if not isinstance(v, list) or len(cast(list[Any], v)) > MAX_ROWS:
                raise LayoutError(f"{where}: must be a list of at most {MAX_ROWS} items.")
            return [self.cell(x, f"{where}/{i}") for i, x in enumerate(cast(list[Any], v))]
        if kind == "pairs":
            if not isinstance(v, list) or len(cast(list[Any], v)) > MAX_ROWS:
                raise LayoutError(f"{where}: must be a list of at most {MAX_ROWS} label and value pairs.")
            out: list[dict[str, Any]] = []
            for i, p in enumerate(cast(list[Any], v)):
                if not isinstance(p, dict) or set(cast(dict[str, Any], p)) - {"label", "value"}:
                    raise LayoutError(f"{where}/{i}: must be an object with label and value only.")
                pd = cast(dict[str, Any], p)
                out.append(
                    {
                        "label": self.text_of(pd.get("label"), f"{where}/{i}/label"),
                        "value": self.cell(pd.get("value"), f"{where}/{i}/value"),
                    }
                )
            return out
        if kind == "rows":
            if not isinstance(v, list) or len(cast(list[Any], v)) > MAX_ROWS:
                raise LayoutError(f"{where}: must be a list of at most {MAX_ROWS} rows.")
            rows: list[dict[str, Any]] = []
            for i, r in enumerate(cast(list[Any], v)):
                if not isinstance(r, dict) or len(cast(dict[str, Any], r)) > MAX_COLUMNS:
                    raise LayoutError(f"{where}/{i}: must be a flat object with at most {MAX_COLUMNS} keys.")
                rows.append(
                    {
                        self.text_of(k, f"{where}/{i}"): self.cell(c, f"{where}/{i}/{k}")
                        for k, c in cast(dict[str, Any], r).items()
                    }
                )
            return rows
        if kind == "columns":
            if not isinstance(v, list) or not 0 < len(cast(list[Any], v)) <= MAX_COLUMNS:
                raise LayoutError(f"{where}: must list 1 to {MAX_COLUMNS} columns.")
            cols: list[dict[str, Any]] = []
            for i, c in enumerate(cast(list[Any], v)):
                cd = cast(dict[str, Any], c) if isinstance(c, dict) else {}
                if not cd or "key" not in cd or set(cd) - {"key", "label", "format"}:
                    raise LayoutError(f"{where}/{i}: must be an object with key, and optionally label and format.")
                col: dict[str, Any] = {"key": self.text_of(cd["key"], f"{where}/{i}/key")}
                if cd.get("label") is not None:
                    col["label"] = self.text_of(cd["label"], f"{where}/{i}/label")
                if cd.get("format") is not None:
                    if cd["format"] not in FORMATS:
                        raise LayoutError(f"{where}/{i}/format: must be one of {', '.join(FORMATS)}.")
                    col["format"] = cd["format"]
                cols.append(col)
            return cols
        if kind == "reply":
            rd = cast(dict[str, Any], v) if isinstance(v, dict) else {}
            if not rd or "text" not in rd or set(rd) - {"text", "values"}:
                raise LayoutError(f"{where}: must be an object with text, and optionally values.")
            reply: dict[str, Any] = {"text": self.text_of(rd["text"], f"{where}/text")}
            values = rd.get("values")
            if values is not None:
                if not isinstance(values, dict) or len(cast(dict[str, Any], values)) > MAX_COLUMNS:
                    raise LayoutError(f"{where}/values: must be a flat object with at most {MAX_COLUMNS} keys.")
                reply["values"] = {
                    self.text_of(k, f"{where}/values"): self.cell(x, f"{where}/values/{k}")
                    for k, x in cast(dict[str, Any], values).items()
                }
            return reply
        raise LayoutError(f"{where}: unknown field kind.")  # pragma: no cover

    def kind(self, kind: str, value: dict[str, Any], where: str) -> dict[str, Any]:
        """A c-176 kind's node: its fields checked against the kind's schema (closed objects, list and text limits),
        and its text counted toward the layout's total like any other node's."""
        found: list[Any] = list(Draft202012Validator(kinds.SCHEMAS[kind]).iter_errors(value))  # pyright: ignore[reportUnknownMemberType]
        if found:
            e = sorted(found, key=lambda x: [str(p) for p in x.path])[0]
            at = "/".join(str(p) for p in e.path)
            raise LayoutError(f"{where}/{at}: {e.message}" if at else f"{where or kind}: {e.message}")
        for i, t in enumerate(_texts(value)):
            self.text_of(t, f"{where}/text {i}")
        return {"type": kind, **value}

    def node(self, n: Any, depth: int, where: str) -> dict[str, Any] | None:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise LayoutError(f"{where}: a layout may hold at most {MAX_NODES} nodes.")
        if depth > MAX_DEPTH:
            raise LayoutError(f"{where}: a layout may nest at most {MAX_DEPTH} levels.")
        if not isinstance(n, dict):
            raise LayoutError(f"{where}: must be an object with a type.")
        nd = cast(dict[str, Any], n)
        kind = nd.get("type")
        if not isinstance(kind, str) or kind not in CATALOGUE:
            raise LayoutError(f"{where}: type {kind!r} is not in the catalogue ({', '.join(CATALOGUE)}).")
        fields, holds, required = CATALOGUE[kind]
        extra = set(nd) - {"type", *fields, *(("children",) if holds else ())}
        if extra:
            raise LayoutError(f"{where}: {kind} does not take {', '.join(sorted(extra))}.")
        missing = [f for f in required if nd.get(f) is None]
        if missing and self.prune:
            # A filled template whose data left an optional field out: the node that shows it is left out too.
            return None
        if missing:
            raise LayoutError(f"{where}: {kind} needs {', '.join(missing)}.")
        out: dict[str, Any] = {"type": kind}
        if kind in kinds.SCHEMAS and kind not in kinds.PRIMITIVES:
            return self.kind(kind, {k: v for k, v in nd.items() if k != "type" and v is not None}, where)
        for name, fk in fields.items():
            if nd.get(name) is not None:
                out[name] = self.field(fk, nd[name], f"{where}/{name}")
        if kind == "image":
            # Images are blocked (L5): the console draws "[Image blocked: alt]" and never fetches a source.
            if not self.images:
                raise LayoutError(f"{where}: images are blocked for this agent.")
            out.pop("src", None)
        if kind == "button":
            self.buttons += 1
            if self.buttons > MAX_BUTTONS:
                raise LayoutError(f"{where}: a layout may hold at most {MAX_BUTTONS} buttons.")
        if kind == "badge" and "tones" in out:
            out["tone"] = cast(dict[str, str], out.pop("tones")).get(out["text"], out.get("tone", "neutral"))
        if holds:
            kids = nd.get("children", [])
            if not isinstance(kids, list) or len(cast(list[Any], kids)) > MAX_CHILDREN:
                raise LayoutError(f"{where}/children: must be a list of at most {MAX_CHILDREN} nodes.")
            built = [self.node(c, depth + 1, f"{where}/children/{i}") for i, c in enumerate(cast(list[Any], kids))]
            out["children"] = [c for c in built if c is not None]
        return out


def _texts(v: Any) -> list[str]:
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [t for x in cast(dict[str, Any], v).values() for t in _texts(x)]
    if isinstance(v, list):
        return [t for x in cast(list[Any], v) for t in _texts(x)]
    return []


def check(tree: Any, *, images: bool = False) -> dict[str, Any]:
    """The tree rebuilt from catalogue primitives and their closed fields, or a LayoutError naming the node's JSON
    Pointer and the rule it broke. A composed layout carries literal values only, so a `$bind` here is refused as an
    unknown value shape."""
    out = _Walk(images=images).node(tree, 1, "")
    assert out is not None  # without prune a missing field raises
    return out


def _pointer(data: Any, pointer: str) -> Any:
    if pointer == "":
        return data
    if not pointer.startswith("/"):
        raise LayoutError(f"{pointer!r} is not a JSON Pointer.")
    cur = data
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict) and token in cur:
            cur = cast(dict[str, Any], cur)[token]
        elif isinstance(cur, list) and token.isdigit() and int(token) < len(cast(list[Any], cur)):
            cur = cast(list[Any], cur)[int(token)]
        else:
            return None
    return cur


def bind(tree: Any, data: Any) -> Any:
    """The template's tree with each `{"$bind": pointer}` replaced by the value at that pointer in `data` (null when
    the data leaves an optional field out)."""
    if isinstance(tree, dict):
        td = cast(dict[str, Any], tree)
        if set(td) == {"$bind"}:
            return _pointer(data, str(td["$bind"]))
        return {k: bind(v, data) for k, v in td.items()}
    if isinstance(tree, list):
        return [bind(v, data) for v in cast(list[Any], tree)]
    return tree


def check_schema(schema: Any) -> dict[str, Any]:
    """A widget template's data schema: a valid JSON Schema whose root is an object."""
    if not isinstance(schema, dict) or cast(dict[str, Any], schema).get("type") != "object":
        raise LayoutError("A widget's data schema must be a JSON Schema with type object.")
    sd = cast(dict[str, Any], schema)
    try:
        Draft202012Validator.check_schema(sd)
    except SchemaError as e:
        raise LayoutError(f"The data schema is not valid JSON Schema: {e.message}") from e
    return sd


def fill(tree: Any, schema: dict[str, Any], data: Any) -> dict[str, Any]:
    """A published template filled with `data`: the data checked against the template's schema, bound into its tree,
    and the result checked as any composed layout is (the same L3 to L6 limits). A node whose required field the data
    left out is skipped. Images in a template draw blocked."""
    found: list[Any] = list(Draft202012Validator(schema).iter_errors(data))  # pyright: ignore[reportUnknownMemberType]
    errors = sorted(found, key=lambda e: [str(p) for p in e.path])
    if errors:
        e = errors[0]
        at = "/" + "/".join(str(p) for p in e.path) if e.path else "the data"
        raise LayoutError(f"{at}: {e.message}")
    out = _Walk(images=True, prune=True).node(bind(tree, data), 1, "")
    if out is None:
        raise LayoutError("The data leaves nothing for this widget to show.")
    return out


def fields_of(schema: dict[str, Any]) -> str:
    """The template's top-level fields for an error the model can act on: `name (type, required)`, comma-separated."""
    props = cast(dict[str, Any], schema.get("properties") or {})
    required = set(cast(list[str], schema.get("required") or []))
    out: list[str] = []
    for name, spec in props.items():
        kind = cast(dict[str, Any], spec).get("type", "any") if isinstance(spec, dict) else "any"
        out.append(f"{name} ({kind}{', required' if name in required else ''})")
    return ", ".join(out)


def required_tools(tree: Any) -> list[str]:
    """The tools a tree's buttons ask the agent to use (`requires`), in order, without repeats. Works on a template's
    tree (with bindings) and on a checked layout."""
    found: list[str] = []

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            nd = cast(dict[str, Any], n)
            if nd.get("type") == "button" and isinstance(nd.get("requires"), str) and nd["requires"] not in found:
                found.append(nd["requires"])
            for v in nd.values():
                walk(v)
        elif isinstance(n, list):
            for v in cast(list[Any], n):
                walk(v)

    walk(tree)
    return found
