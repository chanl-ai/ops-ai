"""How a person starts a workflow by hand, declared by its trigger type.

A trigger type that a person can start declares a `StartSpec`: what the start dialog is called, how audit names a run
started this way, and the start form as JSON Schema, either fixed (an Email received trigger's test email) or read
from one of the trigger's parameters (a Request trigger's `inputSchema`). The console draws whatever form this returns,
and agents-service hands the filled form to the adapter for the trigger's kind, which builds the input the real source
would and starts the run through the real source's own entry. A new kind of trigger is a registry entry plus an
adapter; the console does not change.

Form widgets come from the schema: `format: "file"` (see `file_shape`), `format: "email"`, `x-widget: "textarea"`, an
`enum` or a `oneOf` of `{const, title}`, and a property's `title` as its label.

`start` is the one way a run is written. It holds the run's input to the schema its trigger declares (`input_schema`)
with `typed_values`, the one rule for a start's values, so every source of a run (an API call, a hosted form, a batch
row, an agent's tool call, a Start workflow step, a service event) is checked the same way and no caller chooses to
skip it. The write itself (`store.new_runs.write_run`) is importable by this module alone: the import contract
`runs-written-by-the-start-entry` in `.importlinter` fails when anything else imports it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

import jsonschema
import jsonschema.exceptions

from ops_service_kit.http import Json, JsonValue

from .store import DefinitionRow, RunRow, RunStore
from .store.new_runs import NewRun, write_run

if TYPE_CHECKING:
    from .node_types import TypeRegistry

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

    def input_schema(self, parameters: Mapping[str, JsonValue]) -> Json | None:
        """The schema a run's input must match: the one the trigger's `form_parameter` holds, or None when it holds
        none. A fixed `form` is not it: its adapter turns the form into the input the real source produces (a test
        email becomes the envelope a mailbox delivers), so the form describes the dialog and not the run's input."""
        raw = parameters.get(self.form_parameter or "")
        return dict(cast(Json, raw)) if isinstance(raw, Mapping) and raw else None

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


class InputRefusedError(ValueError):
    """A start's values its schema refuses. `field` is the schema property (a dotted path below the top), `reason`
    what is wrong with it, `missing` the labels of required fields left empty, and `code` the API's error code."""

    def __init__(
        self,
        message: str,
        *,
        field: str | None,
        reason: str,
        missing: tuple[str, ...] = (),
        code: str = "invalid_input",
    ) -> None:
        super().__init__(message)
        self.field, self.reason, self.missing, self.code = field, reason, missing, code


# The digits 0-9 only (re.ASCII): `\d` and `int()` would also take digits of other scripts. No exponent, no
# thousands separator, and a decimal point needs a digit on both sides.
_INTEGER = re.compile(r"[+-]?[0-9]+", re.ASCII)
_WHOLE = re.compile(r"([+-]?[0-9]+)\.0+", re.ASCII)
_DECIMAL = re.compile(r"[+-]?[0-9]+\.[0-9]+", re.ASCII)
_BOOLEANS = {"true": True, "false": False}
MAX_NUMBER_TEXT = 40
_KINDS = {str: "text", bool: "true or false", int: "a number", float: "a number", list: "a list", dict: "an object"}
_WANTED = {
    "number": "a number",
    "integer": "a whole number",
    "boolean": "true or false",
    "string": "text",
    "array": "a list",
    "object": "an object",
    "null": "empty",
}


def _types(field: Mapping[str, JsonValue]) -> set[str]:
    t = field.get("type")
    return {t} if isinstance(t, str) else {str(x) for x in t} if isinstance(t, list) else set()


def _read(types: set[str], text: str) -> JsonValue:
    """Text as the declared type when it reads exactly as one, else the text unchanged, which the schema then refuses
    naming the field. The rules, written for people in docs/architecture/workflow-runner.md ("Run input"): a field
    that takes text keeps it (only the schema knows a postcode `01234` from the number 1234); spaces around the value
    are dropped; a number is the digits 0-9 with an optional sign and decimal point, at most MAX_NUMBER_TEXT
    characters; a whole-number field also takes a zero fraction (`12.0` is 12); true and false in any case."""
    if "string" in types or not types:
        return text
    t = text.strip()
    if "boolean" in types and t.lower() in _BOOLEANS:
        return _BOOLEANS[t.lower()]
    # Longer than any number a person sends. Python itself refuses to read more than 4,300 digits, and that must not
    # be the server's error.
    if len(t) > MAX_NUMBER_TEXT or not types & {"integer", "number"}:
        return text
    if _INTEGER.fullmatch(t):
        return int(t)
    if "number" in types and _DECIMAL.fullmatch(t):
        return float(t)
    if whole := _WHOLE.fullmatch(t):
        return int(whole.group(1))
    return text


def _typed(field: Mapping[str, JsonValue], value: JsonValue) -> JsonValue:
    """`value` with each text read as its declared type, through objects and lists. A property left empty (null, or
    blank text where the field takes no text) is left out, as a form or a spreadsheet cell sends an empty field."""
    if isinstance(value, str):
        return _read(_types(field), value)
    if isinstance(value, float) and value.is_integer() and _types(field) == {"integer"}:
        # JSON Schema takes 12.0 for a whole number; it is stored as 12, as the text "12.0" is.
        return int(value)
    props = field.get("properties")
    if isinstance(value, dict) and isinstance(props, Mapping):
        out: Json = {}
        for name, item in value.items():
            spec = cast(Json, props).get(name)
            if not isinstance(spec, Mapping):
                out[name] = item
                continue
            types = _types(cast(Json, spec))
            blank = isinstance(item, str) and not item.strip() and bool(types) and "string" not in types
            if (item is None and "null" not in types) or blank:
                continue
            out[name] = _typed(cast(Json, spec), item)
        return out
    items = field.get("items")
    if isinstance(value, list) and isinstance(items, Mapping):
        return [_typed(cast(Json, items), v) for v in value]
    return value


def _refusal(schema: Mapping[str, JsonValue], err: Any) -> InputRefusedError:
    path = [str(p) for p in err.absolute_path]
    if err.validator == "required" and (found := re.match(r"'(.+?)' is a required property", str(err.message))):
        path.append(found.group(1))
    field = ".".join(path) or None
    top = cast(Json, cast(Json, schema.get("properties") or {}).get(path[0]) or {}) if path else {}
    label = str(top.get("title") or path[0]) if len(path) == 1 else field or "The input"
    if err.validator == "type":
        value: Any = err.validator_value
        wanted = cast(list[Any], value if isinstance(value, list) else [value])
        names = " or ".join(_WANTED.get(str(w), str(w)) for w in wanted)
        sent = cast(type[Any], type(err.instance))
        got = "empty" if err.instance is None else _KINDS.get(sent, "another kind of value")
        reason = f"must be {names}, and {got} was sent"
    elif err.validator == "required":
        reason = "is required"
    else:
        reason = str(err.message)
        return InputRefusedError(f"{label}: {reason}.", field=field, reason=reason)
    return InputRefusedError(f"{label} {reason}.", field=field, reason=reason)


def typed_values(schema: Mapping[str, JsonValue], values: Mapping[str, JsonValue]) -> Json:
    """A start's values as a run takes them, or InputRefusedError naming the field and the reason. The one rule for a
    start's values, in this order: the schema must itself be JSON Schema, checked before anything reads it; defaults
    and required fields (`form_values`); text that reads exactly as its
    field's declared number, whole number or true/false becomes that; then the schema is held as JSON Schema. Running
    it again on its own result changes nothing, so a caller that must refuse before it writes anything else (a hosted
    form before it counts against its daily cap, a batch before it stores a row) calls it too."""
    try:
        cast(Any, jsonschema.Draft202012Validator).check_schema(dict(schema))
    except jsonschema.SchemaError as e:
        # A schema saved before `input_schema_invalid` was checked at save: nothing can be held to it, so nothing runs.
        reason = f"the trigger's input schema is not valid JSON Schema ({e.message})"
        raise InputRefusedError(
            f"No run starts: {reason}.", field=None, reason=reason, code="input_schema_invalid"
        ) from e
    out, missing = form_values(schema, values)
    if missing:
        required = cast(list[JsonValue], schema.get("required") or [])
        empty = [str(k) for k in required if _empty(out.get(str(k)))]
        raise InputRefusedError(
            f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} required.",
            field=empty[0] if empty else missing[0],
            reason="is required",
            missing=tuple(missing),
        )
    out = cast(Json, _typed(schema, out))
    err: Any = cast(Any, jsonschema.exceptions).best_match(
        cast(Any, jsonschema.Draft202012Validator(dict(schema))).iter_errors(out)
    )
    if err is not None:
        raise _refusal(schema, err)
    return out


def input_schema(definition: Mapping[str, JsonValue] | None, registry: TypeRegistry) -> Json | None:
    """The schema the definition's trigger declares for a run's input (`StartSpec.input_schema`), or None."""
    node = trigger_node(definition)
    if node is None:
        return None
    t = registry.find(str(node.get("type")), int(cast("str | int | float", node.get("typeVersion") or 1)))
    if t is None or t.start is None:
        return None
    return t.start.input_schema(cast(Mapping[str, JsonValue], node.get("parameters") or {}))


def run_input(
    definition: Mapping[str, JsonValue] | None, values: Mapping[str, JsonValue], registry: TypeRegistry
) -> Json:
    """`values` as a run on `definition` takes them (`typed_values` on its trigger's schema), unchanged when the
    trigger declares none."""
    schema = input_schema(definition, registry)
    return dict(values) if schema is None else typed_values(schema, values)


async def start(runs: RunStore, stored: DefinitionRow, run: NewRun, registry: TypeRegistry) -> tuple[RunRow, bool]:
    """Writes `run` on `stored` with its input held to the trigger's schema, or returns the run that already has its
    key (`store.new_runs.write_run`). InputRefusedError when the input does not match, and then nothing is written."""
    typed = run_input(stored.definition, run["input"], registry)
    return await write_run(runs.tx, {**run, "input": typed})
