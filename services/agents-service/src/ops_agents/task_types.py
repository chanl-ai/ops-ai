"""Human Task types (c-288): what a task screen asks and offers, as a versioned record a review step or an API caller
picks by id and version and fills with params. The screen reads only the type and the params, so no task has code of
its own.

A type version holds `params` (a JSON Schema object; each property may carry a `fallback` line used while it is
missing), `regions` (an ordered list over the fixed REGIONS, each binding its slots to templates over the params) and
`actions` (the decisions offered, each leading to an out port of the step, with the consequence a person reads before
choosing it). A missing required param never refuses a task: it is a warning and the region shows the fallback line
(owner, 2026-10-18). A param of the wrong kind from an API caller is refused, since no fallback can show it.

A template is a string over the params: `{path}` is replaced by the value at that dotted path, and a template that is
exactly one `{path}` binds the value itself (a list of facts stays a list). Binding happens here, on the server, so
the console draws region data and never evaluates a template.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast

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
Say = Callable[[Any], str]


class TypeDefinitionError(ValueError):
    """A type version that cannot be drawn: an unknown region or slot, a duplicate action, a bad tone."""


def seeds() -> list[dict[str, Any]]:
    """The general types every tenant reads: `[{id, version, name, description, params, regions, actions}]`."""
    return cast(list[dict[str, Any]], json.loads(SEED_FILE.read_text()))


def valid_id(type_id: str) -> bool:
    return bool(_ID.match(type_id))


def check_definition(record: dict[str, Any]) -> None:
    """Refuses a version the renderer could not draw; says which part is wrong."""
    raw = record.get("params")
    if not isinstance(raw, dict):
        raise TypeDefinitionError("params must be a JSON Schema object")
    params = cast(dict[str, Any], raw)
    if params.get("type", "object") != "object":
        raise TypeDefinitionError("params must be a JSON Schema object")
    props = cast(dict[str, Any], params.get("properties") or {})
    for name, prop in props.items():
        kind = cast(dict[str, Any], prop).get("type") if isinstance(prop, dict) else None
        if kind is not None and kind not in KINDS:
            raise TypeDefinitionError(f"params.{name}: unknown type {kind}")
    for name in cast(list[Any], params.get("required") or []):
        if name not in props:
            raise TypeDefinitionError(f"params.required names {name}, which params does not declare")
    regions = record.get("regions")
    if not isinstance(regions, list) or not regions:
        raise TypeDefinitionError("regions must list at least one region")
    for i, r in enumerate(cast(list[Any], regions)):
        if not isinstance(r, dict) or cast(dict[str, Any], r).get("region") not in REGIONS:
            raise TypeDefinitionError(f"regions[{i}]: region must be one of {', '.join(REGIONS)}")
        region = cast(dict[str, Any], r)
        slots = REGIONS[str(region["region"])]
        for slot in cast(dict[str, Any], region.get("bind") or {}):
            if slot not in slots:
                raise TypeDefinitionError(f"regions[{i}].bind.{slot}: {region['region']} binds {', '.join(slots)}")
    actions = record.get("actions")
    if not isinstance(actions, list) or not actions:
        raise TypeDefinitionError("actions must list at least one action")
    seen: set[str] = set()
    for i, a in enumerate(cast(list[Any], actions)):
        action = cast(dict[str, Any], a) if isinstance(a, dict) else {}
        if not action.get("name") or not action.get("port"):
            raise TypeDefinitionError(f"actions[{i}]: name and port are required")
        if action["name"] in seen:
            raise TypeDefinitionError(f"actions[{i}]: {action['name']} is listed twice")
        seen.add(str(action["name"]))
        if action.get("reason", "none") not in REASONS:
            raise TypeDefinitionError(f"actions[{i}].reason must be one of {', '.join(REASONS)}")
        if action.get("tone", "neutral") not in TONES:
            raise TypeDefinitionError(f"actions[{i}].tone must be one of {', '.join(TONES)}")


def _kind_ok(value: Any, kind: str) -> bool:
    # bool is an int in Python; a true/false is never a number here.
    if isinstance(value, bool) and kind in ("number", "integer"):
        return False
    return isinstance(value, KINDS[kind])


def check_params(record: dict[str, Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    """`[{field, severity, message}]`: a missing required param is a warning (its fallback is shown), a value of the
    wrong kind an error. The caller decides what an error does: the task API refuses it, a paused run shows it."""
    schema = cast(dict[str, Any], record.get("params") or {})
    props = cast(dict[str, Any], schema.get("properties") or {})
    out: list[dict[str, Any]] = []
    for name in cast(list[str], schema.get("required") or []):
        if params.get(name) in (None, "", []):
            out.append({"field": name, "severity": "warning", "message": f"{name} is missing; the fallback is shown"})
    for name, value in params.items():
        kind = cast(dict[str, Any], props.get(name) or {}).get("type")
        if value is not None and kind and not _kind_ok(value, str(kind)):
            out.append({"field": name, "severity": "error", "message": f"{name} must be {kind}"})
    return out


def _at(params: dict[str, Any], path: str) -> Any:
    cur: Any = params
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cast(dict[str, Any], cur).get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cast(list[Any], cur)):
            cur = cast(list[Any], cur)[int(part)]
        else:
            return None
    return cur


def fill(template: Any, params: dict[str, Any], say: Say = str) -> Any:
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


def _fallbacks(record: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Params with each missing one replaced by its `fallback` line, itself a template over the others and the type's
    name (`{typeName}`)."""
    props = cast(dict[str, Any], cast(dict[str, Any], record.get("params") or {}).get("properties") or {})
    base = {**params, "typeName": record.get("name")}
    filled = dict(params)
    for name, prop in props.items():
        fb = cast(dict[str, Any], prop).get("fallback") if isinstance(prop, dict) else None
        if fb is not None and params.get(name) in (None, "", []):
            filled[name] = fill(fb, base)
    return filled


def _boxes(fields: Any) -> list[dict[str, Any]]:
    """The document region's boxes from the fields it is bound to, as an Extract from file step reads them (a dict by
    field key, each with its `boxes` and `needsReview`) or as a list of `{key, boxes, check}`: one flat
    `{key, page, x, y, w, h, check}` per box, so the viewer draws them on its own."""
    if isinstance(fields, dict):
        items = [
            {"key": k, **cast(dict[str, Any], f)}
            for k, f in cast(dict[str, Any], fields).items()
            if isinstance(f, dict)
        ]
    elif isinstance(fields, list):
        items = [cast(dict[str, Any], f) for f in cast(list[Any], fields) if isinstance(f, dict)]
    else:
        return []
    out: list[dict[str, Any]] = []
    for field in items:
        check = bool(field.get("check") or field.get("needsReview"))
        for b in cast(list[Any], field.get("boxes") or []):
            if isinstance(b, dict):
                box = cast(dict[str, Any], b)
                out.append(
                    {"key": field.get("key"), **{k: box.get(k) for k in ("page", "x", "y", "w", "h")}, "check": check}
                )
    return out


def _worded(slot: str, value: Any, say: Say) -> Any:
    """A slot's value as the screen shows it: a text as filled, and each fact's value worded, so no region shows a
    raw date or float. Other values (a file id, fields, a call) are drawn by their region from their own shape."""
    if slot == "facts" and isinstance(value, list):
        return [
            {**cast(dict[str, Any], f), "value": say(cast(dict[str, Any], f).get("value"))}
            if isinstance(f, dict)
            else f
            for f in cast(list[Any], value)
        ]
    return value


def bind(record: dict[str, Any], params: dict[str, Any], say: Say = str) -> dict[str, Any]:
    """What the screen draws: `{regions: [{region, collapsed, data}], actions: [...]}`. A region whose slots all come
    out empty is left out, so a task never shows an empty card. `say` words each value a person reads."""
    p = _fallbacks(record, params)
    regions: list[dict[str, Any]] = []
    for r in cast(list[dict[str, Any]], record.get("regions") or []):
        when = r.get("when")
        if when is not None and fill(when, p) in (None, "", False, []):
            continue
        data = {
            slot: _worded(slot, fill(t, p, say), say) for slot, t in cast(dict[str, Any], r.get("bind") or {}).items()
        }
        if r["region"] == "document" and data.get("boxes") is not None:
            data["boxes"] = _boxes(data["boxes"])
        if all(v in (None, "", []) for v in data.values()):
            continue
        regions.append({"region": r["region"], "collapsed": bool(r.get("collapsed")), "data": data})
    actions: list[dict[str, Any]] = [
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
        for a in cast(list[dict[str, Any]], record.get("actions") or [])
    ]
    return {"regions": regions, "actions": actions}
