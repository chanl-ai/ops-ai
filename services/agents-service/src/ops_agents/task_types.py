"""Human Task types: what a task screen asks and offers, as a versioned record a review step or an API caller
picks by id and version and fills with params. The screen reads only the type and the params, so no task has code of
its own.

A type version holds `params` (a JSON Schema object; each property may carry a `fallback` line used while it is
missing), `regions` (an ordered list over the fixed REGIONS, each binding its slots to templates over the params) and
`actions` (the decisions offered, each leading to an out port of the step, with the consequence a person reads before
choosing it). A missing required param never refuses a task: it is a warning and the region shows the fallback line. A
param of the wrong kind from an API caller is refused, since no fallback can show it.

A template is a string over the params: `{path}` is replaced by the value at that dotted path, and a template that is
exactly one `{path}` binds the value itself (a list of facts stays a list). Binding happens here, on the server, so
the console draws region data and never evaluates a template.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from ops_service_kit.http import Json, JsonList, JsonValue

# The regions a type may list, and the slots each one binds. The console draws each with one renderer.
REGIONS: dict[str, tuple[str, ...]] = {
    "header": ("title",),
    "why_source": ("why", "source"),
    "document": ("file", "received", "boxes"),
    "facts": ("facts",),
    "write_preview": ("call",),
    "form": ("fields",),
    "message": ("text",),
    "history": ("events",),
    # The cases a task's run and its child runs opened, each linked (filled by the server: task_view.run_cases).
    "cases": ("cases",),
}
REASONS = ("required", "optional", "none")
TONES = ("primary", "neutral", "destructive")
# JSON Schema kinds a param may declare, and the Python values each accepts.
KINDS: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}
SEED_FILE = Path(__file__).resolve().parents[2] / "seed" / "task_types.json"
_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_PLACE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\}")

Severity = Literal["warning", "error"]
# How a value placed in a task's text reads; str by default, the API layer passes the reviewer wording.
Say = Callable[[JsonValue], str]


class TaskTypeRecord(TypedDict, total=False):
    """A task type version as stored. Each key is typed as every writer has let it through since the first release
    (the save and create routes' `Definition` model, then `check_definition`, and the seed file): a name and
    description as text, `params` an object, `regions` and `actions` lists of objects. What a team wrote inside them
    (a JSON Schema, a region's bindings, an action's wording) stays JSON, read as `check_definition` lets it through.
    Read as a view, not checked: a record of another shape reads, answers or raises exactly as it always has."""

    name: str
    description: str
    params: Json
    regions: list[Json]
    actions: list[Json]
    defaults: Json


class TypeDefinitionError(ValueError):
    """A type version that cannot be drawn: an unknown region or slot, a duplicate action, a bad tone."""


def seeds() -> list[dict[str, Any]]:
    """The general types every tenant reads: `[{id, version, name, description, params, regions, actions}]`. Loose
    as the store's `ensure_seeds` takes them."""
    return cast(list[dict[str, Any]], json.loads(SEED_FILE.read_text()))


def valid_id(type_id: str) -> bool:
    return bool(_ID.match(type_id))


def check_definition(record: Json) -> None:
    """Refuses a version the renderer could not draw; says which part is wrong. `record` is a request's body, not yet
    saved, so it is read part by part as it arrives."""
    params = record.get("params")
    if not isinstance(params, dict):
        raise TypeDefinitionError("params must be a JSON Schema object")
    if params.get("type", "object") != "object":
        raise TypeDefinitionError("params must be a JSON Schema object")
    props = cast(Json, params.get("properties") or {})
    for name, prop in props.items():
        kind = prop.get("type") if isinstance(prop, dict) else None
        if kind is not None and kind not in KINDS:
            raise TypeDefinitionError(f"params.{name}: unknown type {kind}")
    for name in cast(JsonList, params.get("required") or []):
        if name not in props:
            raise TypeDefinitionError(f"params.required names {name}, which params does not declare")
    regions = record.get("regions")
    if not isinstance(regions, list) or not regions:
        raise TypeDefinitionError("regions must list at least one region")
    for i, region in enumerate(regions):
        if not isinstance(region, dict) or region.get("region") not in REGIONS:
            raise TypeDefinitionError(f"regions[{i}]: region must be one of {', '.join(REGIONS)}")
        slots = REGIONS[str(region["region"])]
        for slot in cast(Json, region.get("bind") or {}):
            if slot not in slots:
                raise TypeDefinitionError(f"regions[{i}].bind.{slot}: {region['region']} binds {', '.join(slots)}")
    actions = record.get("actions")
    if not isinstance(actions, list) or not actions:
        raise TypeDefinitionError("actions must list at least one action")
    seen: set[str] = set()
    for i, a in enumerate(actions):
        action: Json = a if isinstance(a, dict) else {}
        if not action.get("name") or not action.get("port"):
            raise TypeDefinitionError(f"actions[{i}]: name and port are required")
        if action["name"] in seen:
            raise TypeDefinitionError(f"actions[{i}]: {action['name']} is listed twice")
        seen.add(str(action["name"]))
        if action.get("reason", "none") not in REASONS:
            raise TypeDefinitionError(f"actions[{i}].reason must be one of {', '.join(REASONS)}")
        if action.get("tone", "neutral") not in TONES:
            raise TypeDefinitionError(f"actions[{i}].tone must be one of {', '.join(TONES)}")


def _kind_ok(value: JsonValue, kind: str) -> bool:
    # bool is an int in Python; a true/false is never a number here.
    if isinstance(value, bool) and kind in ("number", "integer"):
        return False
    return isinstance(value, KINDS[kind])


def check_params(record: Json, params: dict[str, Any]) -> list[dict[str, Any]]:
    """`[{field, severity, message}]`: a missing required param is a warning (its fallback is shown), a value of the
    wrong kind an error. The caller decides what an error does: the task API refuses it, a paused run shows it.
    `params` is what a step or an API caller wrote, read as it always was: a value of another type raises. The params
    and the issues stay loose here: the task API reads each issue's text as a string, the task view reads the issues
    as JSON and passes params with its run's cases added."""
    schema = cast(TaskTypeRecord, record).get("params") or {}
    props = cast(Json, schema.get("properties") or {})
    out: list[dict[str, Any]] = []
    for name in cast(list[str], schema.get("required") or []):
        if params.get(name) in (None, "", []):
            out.append({"field": name, "severity": "warning", "message": f"{name} is missing; the fallback is shown"})
    for name, value in params.items():
        kind = cast(Json, props.get(name) or {}).get("type")
        if value is not None and kind and not _kind_ok(value, str(kind)):
            out.append({"field": name, "severity": "error", "message": f"{name} must be {kind}"})
    return out


def _at(params: Json, path: str) -> JsonValue:
    cur: JsonValue = params
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def fill(template: JsonValue, params: Json, say: Say = str) -> JsonValue:
    """A template's value over `params`; None when every path it names is missing. A value placed in a text is worded
    by `say` (a date as a person reads it, not its ISO form); a whole-template value is returned as it is."""
    if not isinstance(template, str):
        return template
    whole = _PLACE.fullmatch(template)
    if whole:
        return _at(params, whole.group(1))
    names = _PLACE.findall(template)
    if names and all(_at(params, n) in (None, "") for n in names):
        return None
    return _PLACE.sub(lambda m: "" if (v := _at(params, m.group(1))) is None else say(v), template)


def _fallbacks(record: TaskTypeRecord, params: Json) -> Json:
    """Params with each missing one replaced by its `fallback` line, itself a template over the others and the type's
    name (`{typeName}`)."""
    props = cast(Json, (record.get("params") or {}).get("properties") or {})
    base: Json = {**params, "typeName": record.get("name")}
    filled = dict(params)
    for name, prop in props.items():
        fb = prop.get("fallback") if isinstance(prop, dict) else None
        if fb is not None and params.get(name) in (None, "", []):
            filled[name] = fill(fb, base)
    return filled


def _boxes(fields: JsonValue) -> JsonList:
    """The document region's boxes from the fields it is bound to, as an Extract from file step reads them (a dict by
    field key, each with its `boxes` and `needsReview`) or as a list of `{key, boxes, check}`: one flat
    `{key, page, x, y, w, h, check}` per box, so the viewer draws them on its own."""
    if isinstance(fields, dict):
        items: list[Json] = [{"key": k, **f} for k, f in fields.items() if isinstance(f, dict)]
    elif isinstance(fields, list):
        items = [f for f in fields if isinstance(f, dict)]
    else:
        return []
    out: JsonList = []
    for field in items:
        check = bool(field.get("check") or field.get("needsReview"))
        for box in cast(JsonList, field.get("boxes") or []):
            if isinstance(box, dict):
                out.append(
                    {"key": field.get("key"), **{k: box.get(k) for k in ("page", "x", "y", "w", "h")}, "check": check}
                )
    return out


def _worded(slot: str, value: JsonValue, say: Say) -> JsonValue:
    """A slot's value as the screen shows it: a text as filled, and each fact's value worded, so no region shows a
    raw date or float. Other values (a file id, fields, a call) are drawn by their region from their own shape."""
    if slot == "facts" and isinstance(value, list):
        facts: JsonList = [{**f, "value": say(f.get("value"))} if isinstance(f, dict) else f for f in value]
        return facts
    return value


def bind(record: Json, params: dict[str, Any], say: Say = str) -> dict[str, Any]:
    """What the screen draws: `{regions: [{region, collapsed, data}], actions: [...]}`. A region whose slots all come
    out empty is left out, so a task never shows an empty card. `say` words each value a person reads. `params` is
    what a step or an API caller wrote, read as it always was; params and the reply stay loose for the task view,
    which adds its run's cases to the params and edits the regions it gets back."""
    doc = cast(TaskTypeRecord, record)
    p = _fallbacks(doc, params)
    regions: list[Json] = []
    for r in doc.get("regions") or []:
        when = r.get("when")
        if when is not None and fill(when, p) in (None, "", False, []):
            continue
        data: Json = {slot: _worded(slot, fill(t, p, say), say) for slot, t in cast(Json, r.get("bind") or {}).items()}
        if r["region"] == "document" and data.get("boxes") is not None:
            data["boxes"] = _boxes(data["boxes"])
        if all(v in (None, "", []) for v in data.values()):
            continue
        regions.append({"region": r["region"], "collapsed": bool(r.get("collapsed")), "data": data})
    actions: list[Json] = [
        {
            "name": a["name"],
            "label": a.get("label") or str(a["name"]).capitalize(),
            "consequence": fill(a.get("consequence"), p, say),
            "reason": a.get("reason", "none"),
            "tone": a.get("tone", "neutral"),
            "port": a["port"],
            "inputs": a.get("inputs") or [],
            "requires": a.get("requires"),
        }
        for a in doc.get("actions") or []
    ]
    return {"regions": regions, "actions": actions}
