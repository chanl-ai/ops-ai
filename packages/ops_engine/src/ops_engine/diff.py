"""What changed between two workflow definitions, step by step, for the editor's Versions tab and its publish dialog.

Pure: two stored definitions in, the steps added, removed and changed out. A changed step lists every setting that
differs (a parameter, its name, its type or version, its error route), each with the old and the new value, so no
changed setting goes unshown. A step that only moved on the canvas is listed under `moved`, never under `changed`.
Whether a change needs a review is the publish policy's to say, not this module's.
"""

from __future__ import annotations

from typing import TypedDict, cast

from pydantic import JsonValue

from ops_service_kit.http import Json

# Node keys that are not settings: the id names the step, the position is where it sits on the canvas.
_NOT_SETTINGS = frozenset({"id", "position", "parameters"})


class FieldChange(TypedDict):
    # `name`, `type`, `typeVersion`, or `parameters.<key>` for one of its settings.
    field: str
    before: JsonValue
    after: JsonValue


class StepRef(TypedDict):
    id: str
    name: str
    type: str


class StepChange(StepRef):
    fields: list[FieldChange]


class DefinitionDiff(TypedDict):
    added: list[StepRef]
    removed: list[StepRef]
    changed: list[StepChange]
    # Steps whose position alone changed.
    moved: list[StepRef]
    # Connections between steps made and taken away, as "from.port -> to.port".
    connected: list[str]
    disconnected: list[str]
    # Settings of the workflow itself (its name, description), as for a step.
    workflow: list[FieldChange]


def _nodes(definition: Json | None) -> dict[str, Json]:
    raw = (definition or {}).get("nodes")
    nodes = cast(list[JsonValue], raw) if isinstance(raw, list) else []
    return {str(n["id"]): cast(Json, n) for n in nodes if isinstance(n, dict) and n.get("id") is not None}


def _ref(node_id: str, n: Json) -> StepRef:
    return {"id": node_id, "name": str(n.get("name") or node_id), "type": str(n.get("type") or "")}


def _fields(before: Json, after: Json) -> list[FieldChange]:
    out: list[FieldChange] = []
    for key in sorted((before.keys() | after.keys()) - _NOT_SETTINGS):
        if before.get(key) != after.get(key):
            out.append({"field": key, "before": before.get(key), "after": after.get(key)})
    old = cast(Json, before.get("parameters") or {})
    new = cast(Json, after.get("parameters") or {})
    for key in sorted(old.keys() | new.keys()):
        if old.get(key) != new.get(key):
            out.append({"field": f"parameters.{key}", "before": old.get(key), "after": new.get(key)})
    return out


def _wires(definition: Json | None) -> set[str]:
    raw = (definition or {}).get("connections")
    out: set[str] = set()
    for c in cast(list[JsonValue], raw) if isinstance(raw, list) else []:
        if isinstance(c, dict) and isinstance(c.get("from"), dict) and isinstance(c.get("to"), dict):
            f, t = cast(Json, c["from"]), cast(Json, c["to"])
            out.add(f"{f.get('node')}.{f.get('port')} -> {t.get('node')}.{t.get('port')}")
    return out


def diff(old: Json | None, new: Json) -> DefinitionDiff:
    """The changes from `old` (None: nothing before, every step is added) to `new`."""
    before, after = _nodes(old), _nodes(new)
    changed: list[StepChange] = []
    moved: list[StepRef] = []
    for node_id, n in after.items():
        if node_id not in before:
            continue
        if fields := _fields(before[node_id], n):
            changed.append({**_ref(node_id, n), "fields": fields})
        elif before[node_id].get("position") != n.get("position"):
            moved.append(_ref(node_id, n))
    old_wires, new_wires = _wires(old), _wires(new)
    top_before = {k: v for k, v in (old or {}).items() if k not in ("nodes", "connections")}
    top_after = {k: v for k, v in new.items() if k not in ("nodes", "connections")}
    return {
        "added": [_ref(i, n) for i, n in after.items() if i not in before],
        "removed": [_ref(i, n) for i, n in before.items() if i not in after],
        "changed": changed,
        "moved": moved,
        "connected": sorted(new_wires - old_wires),
        "disconnected": sorted(old_wires - new_wires),
        "workflow": _fields(top_before, top_after) if old is not None else [],
    }
