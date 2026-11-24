"""What a workflow step receives: each earlier step's fields, by name and path, with the value the acting team's last
finished run gave it, already joined so the step sheet and its field picker read one reply.

The steps come from the working copy when there is one (as Try step reads it), so a step added since the last version
has fields before it is published. The run is one of the acting team's own, so a shared workflow never shows another
team's values."""

from __future__ import annotations

import json
from typing import Any, cast

from pydantic import ValidationError

from ops_engine import default_registry
from ops_engine.definition import Connection, NodeInstance, WorkflowDefinition, ancestors
from ops_engine.shapes import Ports
from ops_engine.store.runs import RunRow
from ops_service_kit.http import Json

from .review_text import humanize

# A value longer than this is cut, with an ellipsis, so one large output cannot flood the sheet.
SAMPLE_VALUE_MAX_CHARS = 500
TRIGGER = "trigger"


def readable(workflow_id: str, definition: Json) -> Json:
    """The working copy as far as it reads: the save keeps what the canvas holds, so a step drawn but not filled in
    (no type yet) and a line to it are left out here rather than failing the whole sample, as Try step reads nodes."""

    def node(raw: Any) -> NodeInstance | None:
        try:
            return NodeInstance.model_validate(raw)
        except ValidationError:
            return None

    def line(raw: Any) -> Connection | None:
        try:
            return Connection.model_validate(raw)
        except ValidationError:
            return None

    listed, wired = definition.get("nodes"), definition.get("connections")
    nodes = [n for n in (node(r) for r in (listed if isinstance(listed, list) else [])) if n is not None]
    kept = {n.id for n in nodes}
    lines = [c for c in (line(r) for r in (wired if isinstance(wired, list) else [])) if c is not None]
    connections = [c for c in lines if c.source.node in kept and c.target.node in kept]
    return WorkflowDefinition.model_validate(
        {"schemaVersion": 2, "id": workflow_id, "nodes": nodes, "connections": connections}
    ).wire()


def shown(value: Any) -> str | None:
    """A value as the sheet shows it: text as written, anything else as JSON, cut at SAMPLE_VALUE_MAX_CHARS. Masking
    is done before, by the route's `for_people`."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= SAMPLE_VALUE_MAX_CHARS else text[:SAMPLE_VALUE_MAX_CHARS] + "…"


def _label(name: str, schema: Any) -> str:
    title = cast(Json, schema).get("title") if isinstance(schema, dict) else None
    return title if isinstance(title, str) and title else humanize(name)


def _field_names(ports: Ports, output: Any) -> list[tuple[str, Any]]:
    """Every field a step's ports declare, then any other field its last output carried (an open shape), in order."""
    seen: dict[str, Any] = {}
    for shape in ports.values():
        for name, schema in cast(Json, shape.get("properties") or {}).items():
            seen.setdefault(name, schema)
    if isinstance(output, dict):
        for name in cast(Json, output):
            seen.setdefault(name, None)
    return list(seen.items())


def sample_view(
    workflow_id: str,
    definition: Json,
    step: str | None,
    *,
    shapes: dict[str, Ports],
    run: RunRow | None,
    values: Json,
) -> dict[str, Any]:
    """The reply: `saved` is false when the working copy does not hold `step` yet (the sheet asks to save first).
    `values` holds the run's `input` and each node's last `output` by node id, as people may see them."""
    d = WorkflowDefinition.model_validate(definition)
    known = {n.id for n in d.nodes}
    saved = step is None or step in known
    before = ancestors(d, step) if step is not None and saved else known
    # A step the run had that the copy no longer holds is left out by the loop below.
    last = cast(Json, values.get("output") or {})
    registry = default_registry()

    def entry(n: NodeInstance) -> dict[str, Any]:
        t = registry.find(n.type, n.type_version)
        output = last.get(n.id)
        trigger = t is not None and t.group == TRIGGER
        if trigger and output is None:
            output = values.get("input")
        fields: list[dict[str, Any]] = [
            {
                "name": name,
                "label": _label(name, schema),
                "path": f"$.input.{name}" if trigger else f"$.nodes.{n.id}.out.{name}",
                "sample": shown(cast(Json, output).get(name) if isinstance(output, dict) else None),
            }
            for name, schema in _field_names(shapes.get(n.id, {}), output)
        ]
        name = n.name or (t.label if t else n.id)
        return {"id": n.id, "name": name, "kind": t.label if t else None, "installed": t is not None, "fields": fields}

    listed = [entry(n) for n in d.nodes if saved and n.id in before]
    own = next((n for n in d.nodes if n.id == step), None)
    return {
        "workflowId": workflow_id,
        "step": step,
        "saved": saved,
        "run": run and {"id": run.id, "version": run.version, "createdAt": run.created_at},
        "steps": listed,
        # What the step itself gives the steps after it, with its own last value.
        "given": entry(own) if own is not None else None,
    }
