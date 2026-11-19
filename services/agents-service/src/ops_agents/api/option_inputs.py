"""The inputs a reviewer may set when deciding a step with options: validated against the option's
declaration, which the human step derived from the operation's input schema, so a decision can neither add an input
the operation does not take nor send one of the wrong type."""

from __future__ import annotations

from typing import cast

from ops_service_kit.errors import ValidationFailed
from ops_service_kit.http import Json, JsonList, JsonValue

_TYPES: dict[str, tuple[type, ...]] = {
    "number": (int, float),
    "integer": (int,),
    "string": (str,),
    "boolean": (bool,),
}


def _typed(value: JsonValue, declared: str) -> bool:
    if isinstance(value, bool):
        return declared == "boolean"
    return isinstance(value, _TYPES.get(declared, (object,)))


def apply_inputs(option: Json, inputs: Json | None) -> Json:
    """The option's call with the reviewer's `inputs` applied. Unknown, ill-typed or out-of-bounds values are
    refused; a required input with no default and no value is missing."""
    # A checkpointed option, read as before: `dict()` of a non-object call raises or copies its pairs as it did.
    call: Json = dict(cast(Json, option.get("call") or {}))
    if not call:
        raise ValidationFailed(f"The {option.get('name')} option has no call behind it.")
    given: Json = dict(cast(Json, call.get("input") or {}))
    call["input"] = given
    raw: JsonList = list(cast(JsonList, option.get("inputs") or []))
    listed: list[Json] = [dict(cast(Json, d)) for d in raw]
    declared: dict[str, Json] = {str(d["name"]): d for d in listed}
    for key, value in (inputs or {}).items():
        if key not in declared:
            allowed = ", ".join(sorted(declared)) or "none"
            raise ValidationFailed(f"{key} is not an input a reviewer may set on {option.get('name')}: {allowed}.")
        d = declared[key]
        if not _typed(value, str(d.get("type") or "string")):
            raise ValidationFailed(f"{key} must be a {d.get('type')}.")
        if "minimum" in d and isinstance(value, int | float) and value < float(cast(float, d["minimum"])):
            raise ValidationFailed(f"{key} must be at least {d['minimum']}.")
        if "maximum" in d and isinstance(value, int | float) and value > float(cast(float, d["maximum"])):
            raise ValidationFailed(f"{key} must be at most {d['maximum']}.")
        if "enum" in d and value not in list(cast(JsonList, d["enum"])):
            raise ValidationFailed(f"{key} must be one of {', '.join(str(x) for x in cast(JsonList, d['enum']))}.")
        given[key] = value
    for key, d in declared.items():
        if d.get("required") and given.get(key) in (None, ""):
            raise ValidationFailed(f"{key} is needed to {option.get('name')}.")
    return call


def held_calls(payload: Json) -> list[Json]:
    """Every write a review holds: the step's own call, else each option's. Rejecting a write decides it as approving
    does, so whoever rejects must be someone who may approve each of these."""
    if isinstance(call := payload.get("call"), dict):
        return [call]
    options = [o for o in cast(JsonList, payload.get("options") or []) if isinstance(o, dict)]
    return [c for o in options if isinstance(c := o.get("call"), dict) and c.get("tool")]
