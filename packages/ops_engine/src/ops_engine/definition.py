"""Workflow definitions, schema version 2: node instances of registered types joined by port connections.

    schemaVersion: 2
    id: refund_check
    name: Refund check
    nodes:
      - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request, parameters: {}, position: {x: 0, y: 0}}
      - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: done}}
    connections:
      - {from: {node: start, port: payload}, to: {node: done, port: in}}

YAML is accepted where a definition is created and stored as JSON. A parameter value that is a string starting with
`$.` is a path into the run: `$.input.<field>` reads the run's input and `$.nodes.<node id>.out.<field>` an earlier
node's output. In the input of a step that sets `forEach` (Start workflow), `$.item` reads the current item and
`$.index` its position. Definitions with `schemaVersion: 1` are the v1 compiler's (ops_agents.graphs.definition)
and are not read here.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from typing import Any, Literal, cast

import jsonschema
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ops_service_kit.http import Json, JsonList, JsonValue
from ops_service_kit.narrow import json_object

from .node_types import TypeRegistry
from .starts import TRIGGER_GROUP_PREFIX, file_shape

MAPPING_PREFIX = "$."
# Between whole-value paths: `$.a ?? $.b` reads the first that is not empty.
FALLBACK = "??"
# A path inside a text, `Levy notice: {$.input.record.name}`: filled in as text when the step runs.
TEXT_PATH = re.compile(r"\{(\$\.[A-Za-z0-9_.]+)\}")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Position(_Model):
    x: float = 0
    y: float = 0


class NodeInstance(_Model):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    type: str = Field(min_length=1)
    type_version: int = Field(alias="typeVersion", ge=1)
    name: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict[str, Any])
    position: Position = Field(default_factory=Position)


class Endpoint(_Model):
    node: str
    port: str


class Connection(_Model):
    source: Endpoint = Field(alias="from")
    target: Endpoint = Field(alias="to")


class WorkflowDefinition(_Model):
    schema_version: Literal[2] = Field(alias="schemaVersion")
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    name: str = ""
    description: str = ""
    nodes: list[NodeInstance]
    connections: list[Connection] = Field(default_factory=list[Connection])

    def node(self, node_id: str) -> NodeInstance | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def wire(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)

    def digest(self) -> str:
        """SHA-256 of the canonical JSON: one digest names one definition forever."""
        canonical = json.dumps(self.wire(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def targets(self, node_id: str, port: str) -> list[str]:
        return [c.target.node for c in self.connections if c.source.node == node_id and c.source.port == port]


class InvalidDefinitionError(ValueError):
    pass


def parse(source: str | dict[str, Any]) -> WorkflowDefinition:
    """A definition from YAML (or JSON, which YAML reads) text or an already-parsed object."""
    raw: Any = source
    if isinstance(source, str):
        try:
            raw = yaml.safe_load(source)
        except yaml.YAMLError as e:
            raise InvalidDefinitionError(f"not YAML: {e}") from e
    if not isinstance(raw, dict):
        raise InvalidDefinitionError("a definition is an object with schemaVersion, id, nodes and connections")
    if cast(Json, raw).get("schemaVersion") != 2:
        raise InvalidDefinitionError("schemaVersion must be 2; version 1 definitions are published on /v1/graphs")
    try:
        return WorkflowDefinition.model_validate(raw)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors())
        raise InvalidDefinitionError(problems) from e


def mappings(value: Any) -> Iterator[str]:
    """Every path inside a parameter value: whole-value paths and the ones a text carries in braces."""
    if isinstance(value, str):
        if value.startswith(MAPPING_PREFIX):
            yield from (path.strip() for path in value.split(FALLBACK))
        else:
            yield from TEXT_PATH.findall(value)
    elif isinstance(value, dict):
        for v in cast(Json, value).values():
            yield from mappings(v)
    elif isinstance(value, list):
        for v in cast(list[Any], value):
            yield from mappings(v)


def named_by(parameters: Mapping[str, JsonValue]) -> list[tuple[str, str]]:
    """Each node a parameter names by id, with the parameter that names it."""
    out = [(k, str(parameters[k])) for k in ("approves", "approvedBy") if parameters.get(k)]
    for o in cast(JsonList, parameters.get("options") or []):
        if isinstance(o, dict) and isinstance(call := o.get("call"), dict):
            out.append(("options", str(call.get("node"))))
    return out


def named_nodes(parameters: Mapping[str, JsonValue]) -> list[str]:
    """Nodes a parameter names by id: the write a review approves, the review that approves a write."""
    out = [str(parameters[k]) for k in ("approves", "approvedBy") if parameters.get(k)]
    for o in cast(JsonList, parameters.get("options") or []):
        if isinstance(o, dict) and isinstance(call := o.get("call"), dict):
            out.append(str(call.get("node")))
    return out


def referenced_node(path: str) -> str | None:
    """The node a `$.nodes.<id>.out...` path reads; None for `$.input...`."""
    parts = path[len(MAPPING_PREFIX) :].split(".")
    return parts[1] if parts[0] == "nodes" and len(parts) > 1 else None


LOOP_ROOTS = ("item", "index")


def _loop_paths_outside(parameters: Mapping[str, JsonValue]) -> list[str]:
    """`$.item` and `$.index` paths a step uses where no item is: anywhere but the `input` and `label` of a step that
    sets `forEach`. They would read as nothing at run time."""
    looping = parameters.get("forEach") not in (None, "")
    per_item: Json = {"input": parameters.get("input") or {}, "label": parameters.get("label") or ""}
    allowed: set[str] = set(mappings(per_item)) if looping else set()
    return [
        p for p in mappings(parameters) if p[len(MAPPING_PREFIX) :].split(".")[0] in LOOP_ROOTS and p not in allowed
    ]


def _ancestors(d: WorkflowDefinition, node_id: str) -> set[str]:
    """Every node with a path to `node_id`."""
    found: set[str] = set()
    frontier = [node_id]
    while frontier:
        here = frontier.pop()
        for c in d.connections:
            if c.target.node == here and c.source.node not in found:
                found.add(c.source.node)
                frontier.append(c.source.node)
    return found


def ancestors(d: WorkflowDefinition, node_id: str) -> set[str]:
    """Every step a run may have finished before `node_id` starts: the steps whose output it can read."""
    return _ancestors(d, node_id)


def step_name(d: WorkflowDefinition, registry: TypeRegistry, node_id: str) -> str:
    """A step as a builder reads it: the name they gave it, else its type's name, else its id for a step the
    definition does not hold."""
    n = d.node(node_id)
    if n is None:
        return node_id
    if n.name:
        return n.name
    t = registry.find(n.type, n.type_version)
    return t.label if t is not None else node_id


def _way_out(port: str) -> str:
    """A port name in words: `notFound` reads "Not found"."""
    if not port:
        return "unnamed"
    words = re.sub(r"(?<!^)([A-Z])", r" \1", port).replace("_", " ").lower()
    return words[:1].upper() + words[1:]


def _approval_order(d: WorkflowDefinition, known: set[str], registry: TypeRegistry) -> list[Json]:
    """A review approves a write's call as it stands when the review opens, so everything the write's input reads must
    have run before the review, and the review must run before the write. Otherwise a value read as nothing would be
    approved, and the token bound to it."""
    out: list[Json] = []
    for n in d.nodes:
        approved = [str(n.parameters["approves"])] if n.parameters.get("approves") else []
        approved += [
            str(call.get("node"))
            for o in cast(JsonList, n.parameters.get("options") or [])
            if isinstance(o, dict) and isinstance(call := o.get("call"), dict)
        ]
        before = _ancestors(d, n.id)
        for target_id in approved:
            target = d.node(target_id)
            if target is None or target_id not in known:
                continue
            if n.id not in _ancestors(d, target_id):
                reviewer_name, write_name = step_name(d, registry, n.id), step_name(d, registry, target_id)
                msg = f"{reviewer_name} approves {write_name}, which does not follow it."
                out.append(_check(n.id, "approval_order", msg))
            for path in mappings(target.parameters.get("input") or {}):
                ref = referenced_node(path)
                if ref is not None and ref not in before:
                    msg = (
                        f"{step_name(d, registry, target_id)} reads a value from a step that has not run when "
                        f"{step_name(d, registry, n.id)} opens, so it cannot be approved."
                    )
                    out.append(_check(n.id, "approval_order", msg))
    for n in d.nodes:
        reviewer = n.parameters.get("approvedBy")
        if reviewer and str(reviewer) in known and str(reviewer) not in _ancestors(d, n.id):
            reviewer_name = step_name(d, registry, str(reviewer))
            msg = f"{step_name(d, registry, n.id)} is approved by {reviewer_name}, which does not come before it."
            out.append(_check(n.id, "approval_order", msg))
    return out


REQUEST_TRIGGER = "ops.trigger.request"
EVENT_TRIGGER = "ops.trigger.event"
# `$.input.<name>` or `$.input.<name>.fileId`: a whole run input a step reads as a file.
INPUT_FILE_PATH = re.compile(r"^\$\.input\.([A-Za-z0-9_]+)(?:\.fileId)?$")


def _unmarked_file_inputs(d: WorkflowDefinition, registry: TypeRegistry) -> list[Json]:
    """`file_input_unmarked`: a step parameter its type marks `format: "file"` reads a start form's input that the
    trigger's schema does not declare a file field, so the form would ask for a file id in a text box. A
    Request trigger always has a form. A Service event trigger has one only when it declares an input schema. The
    rule reads the node types' schemas, never a field's or step's name."""
    trigger = next(
        (
            n
            for n in d.nodes
            if n.type == REQUEST_TRIGGER or (n.type == EVENT_TRIGGER and n.parameters.get("inputSchema"))
        ),
        None,
    )
    if trigger is None:
        return []
    schema = cast(Json, trigger.parameters.get("inputSchema") or {})
    props = cast(Json, schema.get("properties") or {})
    out: list[Json] = []
    for n in d.nodes:
        t = registry.find(n.type, n.type_version)
        if t is None:
            continue
        for param, spec in cast(Json, t.parameters.get("properties") or {}).items():
            if not isinstance(spec, dict) or json_object(spec).get("format") != "file":
                continue
            for path in mappings(n.parameters.get(param)):
                found = INPUT_FILE_PATH.match(path.strip())
                if found is None:
                    continue
                name = found.group(1)
                field = props.get(name)
                if isinstance(field, dict) and file_shape(json_object(field)):
                    continue
                title = str(json_object(field).get("title") or name) if isinstance(field, dict) else name
                msg = (
                    f"{step_name(d, registry, n.id)} reads {title} as a file, so the trigger's input form must mark "
                    f"{name} "
                    "as a file; otherwise the start form asks for a file id in a text box."
                )
                out.append(_check(trigger.id, "file_input_unmarked", msg, "inputSchema"))
    return out


def _invalid_input_schemas(d: WorkflowDefinition, registry: TypeRegistry) -> list[Json]:
    """`input_schema_invalid`: a trigger's `inputSchema` that is not JSON Schema (a `type` JSON Schema does not have,
    `required` that is not a list). A run's input is held to this schema when it starts, so one that cannot be read
    would refuse every start."""
    out: list[Json] = []
    for n in d.nodes:
        schema = n.parameters.get("inputSchema")
        if not n.type.startswith(TRIGGER_GROUP_PREFIX) or not isinstance(schema, dict) or not schema:
            continue
        try:
            cast(Any, jsonschema.Draft202012Validator).check_schema(schema)
        except jsonschema.SchemaError as e:
            where = ".".join(str(p) for p in e.absolute_path) or "the schema"
            msg = f"The input form of {step_name(d, registry, n.id)} cannot be read ({where}): {e.message}."
            out.append(_check(n.id, "input_schema_invalid", msg, "inputSchema"))
    return out


def _check(node: str | None, code: str, message: str, field: str | None = None, port: str | None = None) -> Json:
    """A check; `port` names the way out or in a connection check is about, so a caller never reads it from the
    message."""
    check: Json = {"node": node, "level": "error", "code": code, "message": message, "field": field}
    return {**check, "port": port} if port is not None else check


# What a JSON type is called in a parameter check, for people who never read the schema.
_TYPE_WORDS = {
    "object": "a group of named values",
    "array": "a list",
    "string": "text",
    "integer": "a whole number",
    "number": "a number",
    "boolean": "on or off",
    "null": "empty",
}


def _form_labels(err: Any, field: str | None, ui: Mapping[str, JsonValue]) -> tuple[list[str], Json]:
    """Where in the form an error is, in the labels the form shows (`Conditions`, `row 2`), and the fields of the entry
    it is in. A list entry reads as its row; a name a person typed (a formula's, a field's) stays as typed."""
    fields = cast(Json, ui.get("fields") or {})
    spec = cast(Json, fields.get(field) or {}) if field else {}
    parts = [str(spec.get("label") or field or "A setting")]
    item = spec.get("item")
    entry = cast(Json, cast(Json, item).get("fields") or {}) if isinstance(item, dict) else {}
    for step in list(cast(list[object], err.path))[1:]:
        if isinstance(step, int):
            parts.append(f"row {step + 1}")
            continue
        sub = cast(Json, entry.get(str(step)) or {})
        parts.append(str(sub.get("label") or step))
        nested = sub.get("item")
        entry = cast(Json, cast(Json, nested).get("fields") or {}) if isinstance(nested, dict) else {}
    return parts, entry


def _plain(err: Any, field: str | None, ui: Mapping[str, JsonValue]) -> str:
    """A schema error as the step's form names it: the setting's label (with its row), then what it must be, in words.
    A setting's schema may say its own problem in `x-problem`; no validator text reaches a builder."""
    parts, entry = _form_labels(err, field, ui)
    rule, value = str(err.validator), cast(object, err.validator_value)
    schema = cast(Json, err.schema)
    # A value inside a setting that has no form of its own (a field list kept as text) names itself by its `title`.
    if rule != "required" and len(parts) > 1 and isinstance(schema.get("title"), str):
        parts[-1] = str(schema["title"])
    where = ", ".join(parts)
    if rule == "required":
        if not err.path:
            return f"{where} is required."
        instance = err.instance
        missing = [k for k in cast(list[str], value) if not isinstance(instance, dict) or k not in instance]
        name = missing[0] if missing else "A value"
        label = str(cast(Json, entry.get(name) or {}).get("label") or name)
        return f"{where}, {label} needs a value."
    if said := schema.get("x-problem"):
        return f"{where} {said}."
    if rule == "type":
        wanted = cast(list[object], value) if isinstance(value, list) else [value]
        return f"{where} must be {' or '.join(_TYPE_WORDS.get(str(w), str(w)) for w in wanted)}."
    if rule == "enum" and isinstance(value, list):
        one_of = schema.get("oneOf")
        titled = [json_object(o) for o in one_of] if isinstance(one_of, list) else []
        words = {str(o["const"]): str(o["title"]) for o in titled if "const" in o and "title" in o}
        return f"{where} must be one of {', '.join(words.get(str(v), str(v)) for v in cast(list[object], value))}."
    if rule == "minLength":
        return f"{where} cannot be empty." if value == 1 else f"{where} needs at least {value} characters."
    if rule == "maxLength":
        return f"{where} is too long: at most {value} characters."
    if rule in ("minimum", "maximum"):
        return f"{where} must be at {'least' if rule == 'minimum' else 'most'} {value}."
    if rule in ("exclusiveMinimum", "exclusiveMaximum"):
        return f"{where} must be {'more' if rule == 'exclusiveMinimum' else 'less'} than {value}."
    if rule in ("minItems", "maxItems"):
        kind = "at least" if rule == "minItems" else "at most"
        return f"{where} needs {kind} {value} {'entry' if value == 1 else 'entries'}."
    if rule == "additionalProperties":
        return f"{where} has a setting this step does not know."
    if rule == "pattern":
        return f"{where} is not in a form this step accepts."
    return f"{where} has a value this step does not accept."


def _parameter(err: Any) -> str | None:
    """The top-level parameter a schema error is about, so an editor can show it under that field: the first path
    segment, or for a missing required property at the top the property's name."""
    if err.path:
        return str(err.path[0])
    if err.validator == "required":
        instance: object = err.instance
        required: list[str] = list(err.validator_value)
        missing = [k for k in required if not isinstance(instance, dict) or k not in instance]
        return str(missing[0]) if missing else None
    return None


def advise(d: WorkflowDefinition, registry: TypeRegistry) -> list[Json]:
    """Warnings that never refuse a save. `fork_without_join`: a step other than a Join reached from two steps one port
    leads to runs once per branch that reaches it; a Join after the branches runs it once."""
    deferred = {n.id for n in d.nodes if (t := registry.find(n.type, n.type_version)) is not None and t.deferred}
    out: list[Json] = []
    warned: set[str] = set()
    for source in {(c.source.node, c.source.port) for c in d.connections}:
        targets = d.targets(*source)
        if len(targets) < 2:
            continue
        reached = [_reach(d, t, stop={source[0], *deferred}) for t in targets]
        for n in d.nodes:
            if n.id in deferred or n.id in warned:
                continue
            # Where two branches meet: two different steps lead into it, each on a different branch. A step further
            # on is reached through that one step and is not warned again.
            inbound = {c.source.node for c in d.connections if c.target.node == n.id}
            per_branch = [
                inbound & (r | ({source[0]} if t == n.id else set())) for t, r in zip(targets, reached, strict=True)
            ]
            meets = any(a - b and b - a for i, a in enumerate(per_branch) for b in per_branch[i + 1 :])
            if not meets:
                continue
            warned.add(n.id)
            msg = (
                f"{step_name(d, registry, n.id)} is reached by several branches from "
                f"{step_name(d, registry, source[0])}, "
                "so it runs once per branch; join them."
            )
            out.append({**_check(n.id, "fork_without_join", msg), "level": "warning"})
    return out


def _reach(d: WorkflowDefinition, start: str, *, stop: set[str]) -> set[str]:
    """The steps reachable from `start`, itself included, not going past a step in `stop`."""
    seen, frontier = {start}, [start]
    while frontier:
        here = frontier.pop()
        if here in stop and here != start:
            continue
        for c in d.connections:
            if c.source.node == here and c.target.node not in seen:
                seen.add(c.target.node)
                frontier.append(c.target.node)
    return seen


def validate(d: WorkflowDefinition, registry: TypeRegistry) -> list[Json]:
    """Per-node checks against the type registry; an empty list means the definition can be compiled. Each check is
    `{node, level, code, message, field}` with `node` None for one about the whole definition and `field` the top-level
    parameter a schema error names, else None."""
    checks: list[Json] = []
    ids = [n.id for n in d.nodes]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        checks.append(_check(dup, "duplicate_node", "Two steps share one id; delete one of them."))
    known = set(ids)
    out_ports: dict[str, list[str]] = {}
    in_ports: dict[str, list[str]] = {}
    triggers: list[str] = []
    for n in d.nodes:
        t = registry.find(n.type, n.type_version)
        if t is None:
            versions = registry.versions(n.type)
            if versions:
                msg = f"{step_name(d, registry, n.id)} uses a version of its step type that is not installed."
                checks.append(_check(n.id, "unknown_type_version", msg))
            else:
                checks.append(
                    _check(n.id, "unknown_type", f"The step type of {step_name(d, registry, n.id)} is not installed.")
                )
            continue
        out_ports[n.id] = t.output_ports(n.parameters)
        named = out_ports[n.id]
        if repeated := sorted({p for p in named if p and named.count(p) > 1}):
            msg = f"{step_name(d, registry, n.id)} has two ways out with the same name: {', '.join(repeated)}."
            checks.append(_check(n.id, "duplicate_port", msg, t.outputs_from, port=repeated[0]))
        in_ports[n.id] = [p.name for p in t.inputs]
        if t.group == "trigger":
            triggers.append(n.id)
        errors = sorted(
            cast(Any, jsonschema.Draft202012Validator(dict(t.parameters))).iter_errors(n.parameters),
            key=lambda e: str(e.path),
        )
        # A wrong choice fails both its `enum` and its `oneOf` titles; the person reads one problem.
        wrong_choice = {tuple(e.absolute_path) for e in errors if e.validator == "enum"}
        for err in errors:
            if err.validator == "oneOf" and tuple(err.absolute_path) in wrong_choice:
                continue
            field = _parameter(err)
            msg = f"{step_name(d, registry, n.id)}: {_plain(err, field, t.ui)}"
            checks.append(_check(n.id, "invalid_parameter", msg, field))
        for param, ref in named_by(n.parameters):
            if ref not in known:
                msg = f"{step_name(d, registry, n.id)} names a step that is no longer in this workflow."
                checks.append(_check(n.id, "unknown_reference", msg, param))
        for path in _loop_paths_outside(n.parameters):
            param = next((k for k, v in n.parameters.items() if path in set(mappings(v))), None)
            msg = f"{step_name(d, registry, n.id)} reads a list item, which only the input of a step with For each has."
            checks.append(_check(n.id, "item_outside_loop", msg, param))
        for param, value in n.parameters.items():
            for path in mappings(value):
                ref = referenced_node(path)
                if ref is not None and ref not in known:
                    msg = f"{step_name(d, registry, n.id)} reads a field of a step that is no longer in this workflow."
                    checks.append(_check(n.id, "unknown_reference", msg, param))
    if not triggers:
        checks.append(_check(None, "no_trigger", "A workflow starts at one trigger; this one has none."))
    elif len(triggers) > 1:
        checks.append(
            _check(
                None,
                "many_triggers",
                f"A workflow has one trigger; found {len(triggers)}: "
                f"{', '.join(step_name(d, registry, i) for i in triggers)}.",
            )
        )
    for c in d.connections:
        s, t_ = c.source, c.target
        if s.node not in known:
            checks.append(_check(None, "unknown_node", "A connection starts at a step that is not in this workflow."))
        elif s.node in out_ports and s.port not in out_ports[s.node]:
            msg = f"A connection leaves {step_name(d, registry, s.node)} by a way out it does not have."
            checks.append(_check(s.node, "unknown_port", msg, port=s.port))
        if t_.node not in known:
            checks.append(_check(None, "unknown_node", "A connection ends at a step that is not in this workflow."))
        elif t_.node in in_ports and t_.port not in in_ports[t_.node]:
            msg = f"A connection enters {step_name(d, registry, t_.node)} by a way in it does not have."
            checks.append(_check(t_.node, "unknown_port", msg, port=t_.port))
    for node_id, ports in out_ports.items():
        for port in ports:
            if not d.targets(node_id, port):
                who = step_name(d, registry, node_id)
                alone = len(ports) == 1
                msg = f"Nothing follows {who}." if alone else f"Nothing follows the {_way_out(port)} way out of {who}."
                checks.append(_check(node_id, "unconnected_port", msg, port=port))
    checks.extend(_approval_order(d, known, registry))
    checks.extend(_unmarked_file_inputs(d, registry))
    checks.extend(_invalid_input_schemas(d, registry))
    for n in d.nodes:
        t = registry.find(n.type, n.type_version)
        sources = {c.source.node for c in d.connections if c.target.node == n.id}
        if t is not None and t.deferred and len(sources) < 2:
            msg = (
                f"{step_name(d, registry, n.id)} joins branches, so it needs connections from at least two steps; "
                f"it has {len(sources)}."
            )
            checks.append(_check(n.id, "join_needs_branches", msg))
    if len(triggers) == 1:
        reached = {triggers[0]}
        frontier = [triggers[0]]
        while frontier:
            here = frontier.pop()
            for c in d.connections:
                if c.source.node == here and c.target.node not in reached:
                    reached.add(c.target.node)
                    frontier.append(c.target.node)
        for n in d.nodes:
            if n.id not in reached:
                checks.append(
                    _check(
                        n.id,
                        "unreachable",
                        f"Nothing leads from {step_name(d, registry, triggers[0])} to {step_name(d, registry, n.id)}.",
                    )
                )
    return checks
