"""What each step's output holds, by the port it leaves by, before the workflow has run (c-353).

A shape is JSON Schema for the step's `out`. A closed shape lists every key the executor can write
(`additionalProperties: false`) and requires the ones it always writes; an open shape lists what is known and lets more
arrive (a tool with no response schema, a request with no input schema, an extraction's document fields). Shapes come
from the node type, the step's own settings, or a lookup into another service (a document type's fields, an
operation's response schema). tests/test_output_shapes.py runs each executor on fake ports and holds what it writes
to what is declared here, so the two cannot drift.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, cast

from . import ai_steps
from .definition import NodeInstance, WorkflowDefinition, mappings
from .node_types import NodeType, TypeRegistry

Shape = dict[str, Any]
Ports = dict[str, Shape]


class Lookups(Protocol):
    """What a shape needs from other services, read as whoever asks for the shapes."""

    async def document_fields(self, type_id: str, version: int | None) -> list[dict[str, Any]]: ...

    async def operation_output(self, operation: str) -> Shape | None: ...


def closed(
    required: tuple[str, ...] = (), optional: tuple[str, ...] = (), props: Mapping[str, Shape] | None = None
) -> Shape:
    typed = dict(props or {})
    properties: dict[str, Shape] = {k: typed.get(k, {}) for k in (*required, *optional)} | typed
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def opened(required: tuple[str, ...] = (), props: Mapping[str, Shape] | None = None) -> Shape:
    shape = closed(required, props=props)
    del shape["additionalProperties"]
    return shape


def is_open(shape: Shape) -> bool:
    return shape.get("additionalProperties") is not False


def mismatches(shape: Shape, out: Any) -> list[str]:
    """What `out` breaks of `shape`: a key a closed shape does not list, or a required key it lacks."""
    if not isinstance(out, Mapping):
        return [f"wrote {type(out).__name__}, not an object"]
    keys = {str(k) for k in cast(Mapping[str, Any], out)}
    problems = [f"requires {k}" for k in cast(list[str], shape.get("required") or []) if k not in keys]
    if not is_open(shape):
        problems += [
            f"undeclared {k}" for k in sorted(keys - set(cast(Mapping[str, Any], shape.get("properties") or {})))
        ]
    return problems


ERROR = closed(("error", "code"))
ANY = opened()

# The Email received trigger's payload (ops_agents email_trigger: messageId to skipped).
EMAIL = closed(
    ("messageId", "from", "subject", "body", "receivedAt", "mailbox", "folder", "attachments", "bodyFile", "skipped")
)


def _keys(value: Any) -> tuple[str, ...]:
    return tuple(str(k) for k in cast(Mapping[str, Any], value)) if isinstance(value, Mapping) else ()


async def _trigger(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    if t.id == "ops.trigger.email":
        return {"payload": EMAIL}
    schema = node.parameters.get("inputSchema")
    return {"payload": cast(Shape, schema) if isinstance(schema, Mapping) and schema else ANY}


async def _set(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    return {"out": closed(_keys(node.parameters.get("values")))}


async def _compute(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    return {"out": closed(_keys(node.parameters.get("expressions"))), "error": ERROR}


async def _if(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    return {"true": closed(("result",)), "false": closed(("result",))}


async def _switch(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    ports = {p: closed(("case",)) for p in t.output_ports(node.parameters) if p != "otherwise"}
    return ports | {"otherwise": closed(("case", "tried"))}


async def _combine(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    fields = [str(f.get("field")) for f in cast(list[Mapping[str, Any]], node.parameters.get("fields") or [])]
    # A source may give fields the step does not list, so its values stay open.
    values = opened(props={f: {} for f in fields})
    out = closed(("values", "sources", "conflicts", "hasConflicts"), props={"values": values})
    return {"out": out, "disagree": out} if node.parameters.get("onDisagreement") == "port" else {"out": out}


async def _match(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    found = closed(("match", "matches", "candidates"))
    return {"matched": found, "none": found}


async def _tool(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    response = await lookups.operation_output(str(node.parameters.get("operation") or ""))
    ports = {
        "ok": response or ANY,
        "refused": closed(("reason",)),
        "error": closed(("error",), ("reason", "cause")),
    }
    if node.parameters.get("onTimeout") == "port":
        ports["timeout"] = closed(("error", "reason"))
    return ports


async def _review(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    decided = closed(("decision", "reason", "by", "approval", "call"), ("edited", "inputs"))
    return dict.fromkeys(t.output_ports(node.parameters), decided)


async def _agent(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    schema = node.parameters.get("outputSchema")
    ok = cast(Shape, schema) if isinstance(schema, Mapping) and schema else closed(("text",))
    return {"ok": ok, "error": ERROR}


async def _ai_prompt(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    params = await ai_steps.resolve_fields(node.parameters, lookups.document_fields)
    answer = ai_steps.JOBS[t.id].schema(params)
    return {p: (ERROR if p == ai_steps.ERROR else answer) for p in t.output_ports(node.parameters)}


async def _extract(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    """Extract's answer is documents-service's read: its fields by key when a document type is named, and more
    (records, what needs review) besides, so it stays open."""
    ref = node.parameters.get("documentType")
    fields: dict[str, Shape] = {}
    typed: Mapping[str, Any] = cast(Mapping[str, Any], ref) if isinstance(ref, Mapping) else {}
    if typed.get("id"):
        listed = await lookups.document_fields(str(typed["id"]), cast(int | None, typed.get("version")))
        fields = {str(f.get("key") or f.get("name")): {} for f in listed}
    read = opened(("extractionId",), props={"fields": opened(props=fields)})
    kind = node.parameters.get("read")
    if kind == "text":
        # The full text and each page's text and tables (c-535): no fields.
        read = closed(("extractionId", "fileId", "text", "pages"), ("readPages", "partial"))
    elif kind == "propose":
        # The keys of a proposed read are known only when the run reads the file, so `fields` stays open (c-535).
        read = opened(("extractionId", "proposal"), props={"fields": opened(), "proposal": opened()})
    others = {
        "error": closed(("error", "code"), ("details",)),
        "timeout": closed(("waitedFor", "key", "seconds", "extractionId")),
    }
    return {p: others.get(p, read) for p in t.output_ports(node.parameters)}


async def _set_file_data(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    return {"ok": closed(("data",)), "error": ERROR}


async def _purge(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    return {"ok": closed(("extractions", "samples"))}


async def _start(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    collected = ("workflowId", "count", "children", "counts")
    ports = {
        "started": closed(("workflowId", "count", "runs")),
        "done": closed(collected),
        "timeout": closed((*collected, "waiting", "notStarted")),
        "error": closed(("error", "code"), ("runs",)),
    }
    return {p: ports[p] for p in t.output_ports(node.parameters)}


async def _case_open(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    return {"opened": closed(("caseId", "created")), "error": ERROR}


async def _case_add(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    return {"added": closed(("caseId",)), "error": ERROR}


async def _wait(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    ports = {"out": closed(optional=("until", "seconds")), "error": closed(("error", "code", "value"))}
    return {p: ports[p] for p in t.output_ports(node.parameters)}


async def _wait_for(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    """Wait for goes on with whatever the outside system posted or the event carried: its answer schema when the step
    sets one, so a Decide step can pick the fields, else any object; the time limit with what it waited for."""
    schema = node.parameters.get("outputSchema")
    ok = cast(Shape, schema) if isinstance(schema, Mapping) and schema else ANY
    return {"ok": ok, "timeout": closed(("waitedFor", "key", "seconds"))}


async def _end(node: NodeInstance, t: NodeType, lookups: Lookups) -> Ports:
    return {"": closed(("outcome", "output"), ("result", "name"))}


Builder = Callable[[NodeInstance, NodeType, Lookups], Awaitable[Ports]]

# By executor, as compiler.EXECUTORS runs them; the Join's shape is its branches' and is built in `shapes`.
BUILDERS: dict[str, Builder] = {
    "trigger.payload": _trigger,
    "data.set": _set,
    "data.compute": _compute,
    "flow.if": _if,
    "flow.switch": _switch,
    "data.combine": _combine,
    "data.match": _match,
    "gateway.call": _tool,
    "review.open": _review,
    "kernel.turn": _agent,
    "ai.prompt": _ai_prompt,
    "ai.extract": _extract,
    "files.setData": _set_file_data,
    "documents.purge": _purge,
    "workflow.start": _start,
    "case.open": _case_open,
    "case.add": _case_add,
    "flow.wait": _wait,
    "flow.wait_for": _wait_for,
    "flow.end": _end,
}


async def shapes(d: WorkflowDefinition, registry: TypeRegistry, lookups: Lookups) -> dict[str, Ports]:
    """Every step's output shape by port. A Join holds each step connected to it, by id, as that step's shape on the
    connected port or null."""
    out: dict[str, Ports] = {}
    joins: list[NodeInstance] = []
    for n in d.nodes:
        t = registry.find(n.type, n.type_version)
        if t is None:
            continue
        if t.deferred:
            joins.append(n)
            continue
        out[n.id] = await BUILDERS[t.executor](n, t, lookups)
    for n in joins:
        branches = {
            c.source.node: {"anyOf": [out.get(c.source.node, {}).get(c.source.port, ANY), {"type": "null"}]}
            for c in d.connections
            if c.target.node == n.id
        }
        out[n.id] = {"out": closed(tuple(branches), props=branches)}
    return out


def _field_of(path: str) -> tuple[str, str] | None:
    """The step and the first output field a `$.nodes.<id>.out.<field>...` path reads; None for any other path."""
    parts = path.removeprefix("$.").split(".")
    if len(parts) >= 4 and parts[0] == "nodes" and parts[2] == "out":
        return parts[1], parts[3].split("[")[0]
    return None


async def unknown_fields(d: WorkflowDefinition, registry: TypeRegistry, lookups: Lookups) -> list[dict[str, Any]]:
    """`unknown_output_field` warnings: a mapping reads a field no port of the step it names can output, every one of
    that step's shapes being closed. A field an open shape may carry is never warned (c-353 Q3)."""
    found = await shapes(d, registry, lookups)
    out: list[dict[str, Any]] = []
    for n in d.nodes:
        for path in mappings(n.parameters):
            read = _field_of(path)
            if read is None or read[0] not in found:
                continue
            step, field = read
            ports = found[step].values()
            if any(is_open(s) or field in (s.get("properties") or {}) for s in ports):
                continue
            message = f"{path} reads {field}, which {step} never outputs."
            out.append(
                {"node": n.id, "level": "warning", "code": "unknown_output_field", "message": message, "field": None}
            )
    return out
