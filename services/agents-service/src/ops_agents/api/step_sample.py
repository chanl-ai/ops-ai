"""What a workflow step receives: each earlier step's fields, by name and path, with the value the acting team's last
finished run gave it, already joined so the step sheet and its field picker read one reply.

The steps come from the working copy when there is one (as Try step reads it), so a step added since the last version
has fields before it is published. The run is one of the acting team's own, so a shared workflow never shows another
team's values."""

from __future__ import annotations

import json
from typing import Any, cast

from ops_agent_kernel.pii import masked
from ops_engine import default_registry
from ops_engine.definition import WorkflowDefinition, ancestors
from ops_engine.shapes import Ports
from ops_engine.store.runs import RunRow, RunStep
from ops_service_kit.http import Json

# A value longer than this is cut, with an ellipsis, so one large output cannot flood the sheet.
SAMPLE_VALUE_MAX_CHARS = 500
TRIGGER = "trigger"


def shown(value: Any, *, mask: bool) -> str | None:
    """A value as the sheet shows it: text as written, anything else as JSON, masked when the team masks personal data
    for people, cut at SAMPLE_VALUE_MAX_CHARS."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if mask:
        text = cast(str, masked(text))
    return text if len(text) <= SAMPLE_VALUE_MAX_CHARS else text[:SAMPLE_VALUE_MAX_CHARS] + "…"


def _label(name: str, schema: Any) -> str:
    title = cast(Json, schema).get("title") if isinstance(schema, dict) else None
    if isinstance(title, str) and title:
        return title
    spaced = "".join(f" {c.lower()}" if c.isupper() else c for c in name).replace("_", " ").strip()
    return spaced[:1].upper() + spaced[1:]


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
    steps: list[RunStep],
    mask: bool,
) -> dict[str, Any]:
    """The reply: `saved` is false when the working copy does not hold `step` yet (the sheet asks to save first)."""
    d = WorkflowDefinition.model_validate(definition)
    known = {n.id for n in d.nodes}
    saved = step is None or step in known
    before = ancestors(d, step) if step is not None and saved else known
    # The last attempt of each node; a step the run had that the copy no longer holds is left out by the loop below.
    last: dict[str, Any] = {}
    for s in steps:
        last[s.node_id] = s.output
    registry = default_registry()
    listed: list[dict[str, Any]] = []
    for n in d.nodes:
        if n.id not in before or not saved:
            continue
        t = registry.find(n.type, n.type_version)
        output = last.get(n.id)
        trigger = t is not None and t.group == TRIGGER
        if trigger and output is None and run is not None:
            output = run.input
        fields: list[dict[str, Any]] = [
            {
                "name": name,
                "label": _label(name, schema),
                "path": f"$.input.{name}" if trigger else f"$.nodes.{n.id}.out.{name}",
                "sample": shown(cast(Json, output).get(name) if isinstance(output, dict) else None, mask=mask),
            }
            for name, schema in _field_names(shapes.get(n.id, {}), output)
        ]
        listed.append(
            {
                "id": n.id,
                "name": n.name or (t.label if t else n.id),
                "kind": t.label if t else None,
                "installed": t is not None,
                "fields": fields,
            }
        )
    return {
        "workflowId": workflow_id,
        "step": step,
        "saved": saved,
        "run": run and {"id": run.id, "version": run.version, "createdAt": run.created_at},
        "steps": listed,
    }
