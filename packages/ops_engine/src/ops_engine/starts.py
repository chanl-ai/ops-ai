"""How a person starts a workflow by hand, declared by its trigger type.

A trigger type that a person can start declares a `StartSpec`: what the start dialog is called, how audit names a run
started this way, and the start form as JSON Schema, either fixed (an Email received trigger's test email) or read
from one of the trigger's parameters (a Request trigger's `inputSchema`). The console draws whatever form this returns,
and agents-service hands the filled form to the adapter for the trigger's kind, which builds the input the real source
would and starts the run through the real source's own entry. A new kind of trigger is a registry entry plus an
adapter; the console does not change.

Form widgets come from the schema: `format: "file"` (see `file_shape`), `format: "email"`, `x-widget: "textarea"`, an
`enum` or a `oneOf` of `{const, title}`, and a property's `title` as its label.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from ops_service_kit.http import Json, JsonValue

FileShape = Literal["id", "one", "many"]
# The Request trigger parameter that keeps a workflow out of every start picker: other workflows start it.
ONLY_FROM_WORKFLOWS = "onlyFromWorkflows"
TRIGGER_GROUP_PREFIX = "ops.trigger."


@dataclass(frozen=True)
class StartSpec:
    """A trigger type's start by hand. `kind` names the adapter that runs it; `via` is how a run started this way reads
    in audit ("test email by <person>"); the form is `form`, or the trigger parameter `form_parameter` names."""

    kind: str
    title: str
    action: str
    via: str
    form: Mapping[str, JsonValue] | None = None
    form_parameter: str | None = None
    # A Service event trigger: Start run exists only when `form_parameter` names a schema with properties. With none,
    # the event is still the only way in.
    when_schema: bool = False

    def schema(self, parameters: Mapping[str, JsonValue]) -> Json:
        if self.form is not None:
            return dict(self.form)
        raw = parameters.get(self.form_parameter or "")
        return dict(cast(Json, raw)) if isinstance(raw, Mapping) and raw else {"type": "object"}

    def view(self, parameters: Mapping[str, JsonValue]) -> Json:
        schema = self.schema(parameters)
        return {
            "kind": self.kind,
            "title": self.title,
            "action": self.action,
            "via": self.via,
            "schema": schema,
            "takesFiles": takes_files(schema),
        }


def file_shape(field: Mapping[str, JsonValue]) -> FileShape | None:
    """A JSON Schema property as a file field: a string with `format: "file"` holds one file's id; an object with
    `format: "file"` or a `fileId` property holds one file as `{fileId, name}`; an array of those holds several."""

    def one(x: Any) -> bool:
        if not isinstance(x, Mapping):
            return False
        s = cast(Json, x)
        props = s.get("properties")
        return s.get("format") == "file" or (
            s.get("type") == "object" and isinstance(props, Mapping) and "fileId" in props
        )

    if field.get("type") == "string" and field.get("format") == "file":
        return "id"
    if one(field):
        return "one"
    if field.get("type") == "array" and one(field.get("items")):
        return "many"
    return None


def file_fields(schema: Mapping[str, JsonValue]) -> dict[str, FileShape]:
    """The schema's top-level file fields by name."""
    props = cast(Json, schema.get("properties") or {})
    out: dict[str, FileShape] = {}
    for name, field in props.items():
        if isinstance(field, Mapping) and (shape := file_shape(cast(Json, field))):
            out[str(name)] = shape
    return out


def takes_files(schema: Mapping[str, JsonValue]) -> bool:
    return bool(file_fields(schema))


def trigger_node(definition: Mapping[str, JsonValue] | None) -> Json | None:
    """The definition's trigger node (a workflow has exactly one), or None for one still being drawn."""
    for node in cast(list[Json], (definition or {}).get("nodes") or []):
        if str(node.get("type") or "").startswith(TRIGGER_GROUP_PREFIX):
            return node
    return None


def only_from_workflows(definition: Mapping[str, JsonValue] | None) -> bool:
    node = trigger_node(definition)
    return bool(node and cast(Json, node.get("parameters") or {}).get(ONLY_FROM_WORKFLOWS))


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value in ([], {})


def form_values(schema: Mapping[str, JsonValue], values: Mapping[str, JsonValue]) -> tuple[Json, list[str]]:
    """A filled start form as a run takes it: each empty field the schema gives a `default` takes it, and the
    required fields still empty, by their labels. The console's start dialog and every API start of a form read the
    same rule, so a start the console refuses is refused by the API too."""
    props = cast(Json, schema.get("properties") or {})
    out = dict(values)
    for name, field in props.items():
        if isinstance(field, Mapping) and "default" in field and _empty(out.get(name)):
            out[str(name)] = cast(Json, field)["default"]
    missing = [
        str(cast(Json, props.get(k) or {}).get("title") or k)
        for k in cast(list[str], schema.get("required") or [])
        if _empty(out.get(k))
    ]
    return out, missing
