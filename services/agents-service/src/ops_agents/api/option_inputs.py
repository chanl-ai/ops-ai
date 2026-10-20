"""The inputs a reviewer may set when deciding a step with options (c-057): validated against the option's
declaration, which the human step derived from the operation's input schema, so a decision can neither add an input
the operation does not take nor send one of the wrong type."""

from __future__ import annotations

from typing import Any, cast

from ops_service_kit.errors import ValidationFailed

_TYPES: dict[str, tuple[type, ...]] = {
    "number": (int, float),
    "integer": (int,),
    "string": (str,),
    "boolean": (bool,),
}


def _typed(value: Any, declared: str) -> bool:
    if isinstance(value, bool):
        return declared == "boolean"
    return isinstance(value, _TYPES.get(declared, (object,)))


def apply_inputs(option: dict[str, Any], inputs: dict[str, Any] | None) -> dict[str, Any]:
    """The option's call with the reviewer's `inputs` applied. Unknown, ill-typed or out-of-bounds values are
    refused; a required input with no default and no value is missing."""
    call: dict[str, Any] = dict(option.get("call") or {})
    if not call:
        raise ValidationFailed(f"The {option.get('name')} option has no call behind it.")
    call["input"] = dict(call.get("input") or {})
    raw: list[Any] = list(option.get("inputs") or [])
    listed: list[dict[str, Any]] = [dict(d) for d in raw]
    declared: dict[str, dict[str, Any]] = {str(d["name"]): d for d in listed}
    for key, value in (inputs or {}).items():
        if key not in declared:
            allowed = ", ".join(sorted(declared)) or "none"
            raise ValidationFailed(f"{key} is not an input a reviewer may set on {option.get('name')}: {allowed}.")
        d = declared[key]
        if not _typed(value, str(d.get("type") or "string")):
            raise ValidationFailed(f"{key} must be a {d.get('type')}.")
        if "minimum" in d and isinstance(value, int | float) and value < float(d["minimum"]):
            raise ValidationFailed(f"{key} must be at least {d['minimum']}.")
        if "maximum" in d and isinstance(value, int | float) and value > float(d["maximum"]):
            raise ValidationFailed(f"{key} must be at most {d['maximum']}.")
        if "enum" in d and value not in list(d["enum"]):
            raise ValidationFailed(f"{key} must be one of {', '.join(str(x) for x in d['enum'])}.")
        call["input"][key] = value
    for key, d in declared.items():
        if d.get("required") and call["input"].get(key) in (None, ""):
            raise ValidationFailed(f"{key} is needed to {option.get('name')}.")
    return call


def held_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every write a review holds: the step's own call, else each option's. Rejecting a write decides it as approving
    does, so whoever rejects must be someone who may approve each of these."""
    if isinstance(payload.get("call"), dict):
        return [cast(dict[str, Any], payload["call"])]
    options = [cast(dict[str, Any], o) for o in cast(list[Any], payload.get("options") or []) if isinstance(o, dict)]
    return [
        cast(dict[str, Any], o["call"]) for o in options if isinstance(o.get("call"), dict) and o["call"].get("tool")
    ]
