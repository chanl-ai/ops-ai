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
from collections.abc import Iterator
from typing import Any, Literal, cast

import jsonschema
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .node_types import TypeRegistry
from .starts import file_shape

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
    if cast(dict[str, Any], raw).get("schemaVersion") != 2:
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
        for v in cast(dict[str, Any], value).values():
            yield from mappings(v)
    elif isinstance(value, list):
        for v in cast(list[Any], value):
            yield from mappings(v)


def named_nodes(parameters: dict[str, Any]) -> list[str]:
    """Nodes a parameter names by id: the write a review approves, the review that approves a write."""
    out = [str(parameters[k]) for k in ("approves", "approvedBy") if parameters.get(k)]
    for o in cast(list[Any], parameters.get("options") or []):
        if isinstance(o, dict) and isinstance(cast(dict[str, Any], o).get("call"), dict):
            out.append(str(cast(dict[str, Any], cast(dict[str, Any], o)["call"]).get("node")))
    return out


def referenced_node(path: str) -> str | None:
    """The node a `$.nodes.<id>.out...` path reads; None for `$.input...`."""
    parts = path[len(MAPPING_PREFIX) :].split(".")
    return parts[1] if parts[0] == "nodes" and len(parts) > 1 else None


LOOP_ROOTS = ("item", "index")


def _loop_paths_outside(parameters: dict[str, Any]) -> list[str]:
    """`$.item` and `$.index` paths a step uses where no item is: anywhere but the `input` and `label` of a step that
    sets `forEach`. They would read as nothing at run time."""
    looping = parameters.get("forEach") not in (None, "")
    per_item: dict[str, Any] = {"input": parameters.get("input") or {}, "label": parameters.get("label") or ""}
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


def _approval_order(d: WorkflowDefinition, known: set[str]) -> list[dict[str, Any]]:
    """A review approves a write's call as it stands when the review opens, so everything the write's input reads must
    have run before the review, and the review must run before the write. Otherwise a value read as nothing would be
    approved, and the token bound to it."""
    out: list[dict[str, Any]] = []
    for n in d.nodes:
        approved = [str(n.parameters["approves"])] if n.parameters.get("approves") else []
        approved += [
            str(cast(dict[str, Any], cast(dict[str, Any], o)["call"]).get("node"))
            for o in cast(list[Any], n.parameters.get("options") or [])
            if isinstance(o, dict) and isinstance(cast(dict[str, Any], o).get("call"), dict)
        ]
        before = _ancestors(d, n.id)
        for target_id in approved:
            target = d.node(target_id)
            if target is None or target_id not in known:
                continue
            if n.id not in _ancestors(d, target_id):
                out.append(_check(n.id, "approval_order", f"{n.id} approves {target_id}, which does not follow it."))
            for path in mappings(target.parameters.get("input") or {}):
                ref = referenced_node(path)
                if ref is not None and ref not in before:
                    msg = f"{target_id} reads {path}, which has not run when {n.id} opens, so it cannot be approved."
                    out.append(_check(n.id, "approval_order", msg))
    for n in d.nodes:
        reviewer = n.parameters.get("approvedBy")
        if reviewer and str(reviewer) in known and str(reviewer) not in _ancestors(d, n.id):
            out.append(_check(n.id, "approval_order", f"{n.id} is approved by {reviewer}, which does not precede it."))
    return out


REQUEST_TRIGGER = "ops.trigger.request"
# `$.input.<name>` or `$.input.<name>.fileId`: a whole run input a step reads as a file.
INPUT_FILE_PATH = re.compile(r"^\$\.input\.([A-Za-z0-9_]+)(?:\.fileId)?$")


def _unmarked_file_inputs(d: WorkflowDefinition, registry: TypeRegistry) -> list[dict[str, Any]]:
    """`file_input_unmarked`: a step parameter its type marks `format: "file"` reads a Request trigger's input that the
    trigger's schema does not declare a file field, so the start form would ask for a file id in a text box (c-466).
    The rule reads the node types' schemas, never a field's or step's name."""
    trigger = next((n for n in d.nodes if n.type == REQUEST_TRIGGER), None)
    if trigger is None:
        return []
    schema = cast(dict[str, Any], trigger.parameters.get("inputSchema") or {})
    props = cast(dict[str, Any], schema.get("properties") or {})
    out: list[dict[str, Any]] = []
    for n in d.nodes:
        t = registry.find(n.type, n.type_version)
        if t is None:
            continue
        for param, spec in cast(dict[str, Any], t.parameters.get("properties") or {}).items():
            if not isinstance(spec, dict) or cast(dict[str, Any], spec).get("format") != "file":
                continue
            for path in mappings(n.parameters.get(param)):
                found = INPUT_FILE_PATH.match(path.strip())
                if found is None:
                    continue
                name = found.group(1)
                field = props.get(name)
                if isinstance(field, dict) and file_shape(cast(dict[str, Any], field)):
                    continue
                title = str(cast(dict[str, Any], field).get("title") or name) if isinstance(field, dict) else name
                msg = (
                    f"{n.id} reads {title} as a file, so the trigger's input must declare {name} a file field "
                    '(format "file"); otherwise the start form asks for a file id in a text box.'
                )
                out.append(_check(trigger.id, "file_input_unmarked", msg, "inputSchema"))
    return out


def _check(node: str | None, code: str, message: str, field: str | None = None) -> dict[str, Any]:
    return {"node": node, "level": "error", "code": code, "message": message, "field": field}


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


def advise(d: WorkflowDefinition, registry: TypeRegistry) -> list[dict[str, Any]]:
    """Warnings that never refuse a save. `fork_without_join`: a step other than a Join reached from two steps one port
    leads to runs once per branch that reaches it (c-278); a Join after the branches runs it once."""
    deferred = {n.id for n in d.nodes if (t := registry.find(n.type, n.type_version)) is not None and t.deferred}
    out: list[dict[str, Any]] = []
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
            msg = f"{n.id} is reached by several branches from {source[0]}, so it runs once per branch; join them."
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


def validate(d: WorkflowDefinition, registry: TypeRegistry) -> list[dict[str, Any]]:
    """Per-node checks against the type registry; an empty list means the definition can be compiled. Each check is
    `{node, level, code, message, field}` with `node` None for one about the whole definition and `field` the top-level
    parameter a schema error names, else None."""
    checks: list[dict[str, Any]] = []
    ids = [n.id for n in d.nodes]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        checks.append(_check(dup, "duplicate_node", f"Two nodes are named {dup}."))
    known = set(ids)
    out_ports: dict[str, list[str]] = {}
    in_ports: dict[str, list[str]] = {}
    triggers: list[str] = []
    for n in d.nodes:
        t = registry.find(n.type, n.type_version)
        if t is None:
            versions = registry.versions(n.type)
            if versions:
                msg = f"{n.type} has no version {n.type_version}; registered: {', '.join(map(str, versions))}."
                checks.append(_check(n.id, "unknown_type_version", msg))
            else:
                checks.append(_check(n.id, "unknown_type", f"No node type {n.type} is registered."))
            continue
        out_ports[n.id] = t.output_ports(n.parameters)
        named = out_ports[n.id]
        if repeated := sorted({p for p in named if named.count(p) > 1}):
            checks.append(_check(n.id, "duplicate_port", f"Each way out has its own name: {', '.join(repeated)}."))
        in_ports[n.id] = [p.name for p in t.inputs]
        if t.group == "trigger":
            triggers.append(n.id)
        errors = sorted(
            cast(Any, jsonschema.Draft202012Validator(dict(t.parameters))).iter_errors(n.parameters),
            key=lambda e: str(e.path),
        )
        for err in errors:
            where = ".".join(str(p) for p in err.path) or "parameters"
            checks.append(_check(n.id, "invalid_parameter", f"{where}: {err.message}", _parameter(err)))
        for ref in named_nodes(n.parameters):
            if ref not in known:
                checks.append(
                    _check(n.id, "unknown_reference", f"{n.id} names node {ref}, which is not in this workflow.")
                )
        for path in mappings(n.parameters):
            ref = referenced_node(path)
            if ref is not None and ref not in known:
                checks.append(
                    _check(n.id, "unknown_reference", f"{path} reads node {ref}, which is not in this workflow.")
                )
        for path in _loop_paths_outside(n.parameters):
            msg = f"{path} reads a list item, which only the input of a step with For each has."
            checks.append(_check(n.id, "item_outside_loop", msg))
    if not triggers:
        checks.append(_check(None, "no_trigger", "A workflow starts at one trigger node; this one has none."))
    elif len(triggers) > 1:
        checks.append(_check(None, "many_triggers", f"A workflow has one trigger; found {', '.join(triggers)}."))
    for c in d.connections:
        s, t_ = c.source, c.target
        if s.node not in known:
            checks.append(_check(None, "unknown_node", f"A connection starts at {s.node}, which is not a node."))
        elif s.node in out_ports and s.port not in out_ports[s.node]:
            checks.append(_check(s.node, "unknown_port", f"{s.node} has no out port {s.port}."))
        if t_.node not in known:
            checks.append(_check(None, "unknown_node", f"A connection ends at {t_.node}, which is not a node."))
        elif t_.node in in_ports and t_.port not in in_ports[t_.node]:
            checks.append(_check(t_.node, "unknown_port", f"{t_.node} has no in port {t_.port}."))
    for node_id, ports in out_ports.items():
        for port in ports:
            if not d.targets(node_id, port):
                checks.append(_check(node_id, "unconnected_port", f"Out port {port} of {node_id} leads nowhere."))
    checks.extend(_approval_order(d, known))
    checks.extend(_unmarked_file_inputs(d, registry))
    for n in d.nodes:
        t = registry.find(n.type, n.type_version)
        sources = {c.source.node for c in d.connections if c.target.node == n.id}
        if t is not None and t.deferred and len(sources) < 2:
            msg = f"{n.id} joins branches, so it needs a connection from at least two steps; it has {len(sources)}."
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
                checks.append(_check(n.id, "unreachable", f"No path from {triggers[0]} reaches {n.id}."))
    return checks
