"""The update rule for a team's copy of a template, as a pure function both agents-service and documents-service call.

Three bodies are compared field by field over the kind's own field list (the store's, never a second list):

- base: the template body the copy was last made or merged against, binding fields left out, no choices applied;
- yours: the copy's newest version;
- template: the template's body now.

| yours vs base | template vs base | Outcome |
|---|---|---|
| same | same | not listed |
| same | changed | taken |
| changed | same | kept |
| changed | changed, equal to yours | not listed |
| changed | changed, different | conflict, yours unless the person chooses the template's |

Binding fields (a copy's name, model, knowledge bases) are the team's and never listed. A copy with no base (made
before the base was stored) lists every field that differs as a conflict kept as yours, so nothing of the team's is
dropped. A field named in `strict` never ends less strict than the team's value when both sides changed it: a list is
the union (a topic the team added stays) and a limit is the smaller one."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

Outcome = Literal["kept", "taken", "conflict"]
Choice = Literal["yours", "template"]
Strictness = Literal["union", "min"]


@dataclass(frozen=True)
class FieldOutcome:
    """One listed field: what happened to it, the team's value, and the value the update would write."""

    field: str
    outcome: Outcome
    yours: Any
    template: Any


def _union(yours: list[Any], template: list[Any]) -> list[Any]:
    return [*yours, *(v for v in template if v not in yours)]


def _strict(rule: Strictness, yours: Any, template: Any) -> Any:
    if rule == "union" and isinstance(yours, list) and isinstance(template, list):
        return _union(list(yours), list(template))  # pyright: ignore[reportUnknownArgumentType]
    if rule == "min" and isinstance(yours, int | float) and isinstance(template, int | float):
        return min(yours, template)
    return yours


def merge(
    base: Mapping[str, Any] | None,
    yours: Mapping[str, Any],
    template: Mapping[str, Any],
    fields: Iterable[str],
    *,
    bindings: Iterable[str] = (),
    strict: Mapping[str, Strictness] | None = None,
) -> list[FieldOutcome]:
    """List each field an update touches, in the order of `fields`.

    Args:
        base: The body the copy was last made or merged against, or None for a copy that has none.
        yours: The copy's newest version.
        template: The template's body now.
        fields: The kind's field list, from its store.
        bindings: Fields the team always keeps; never listed.
        strict: Fields a merge may not loosen, with how a conflict on them resolves.

    Returns:
        One outcome per listed field; a field with nothing to do is left out.
    """
    held = set(bindings)
    rules = strict or {}
    out: list[FieldOutcome] = []
    for f in fields:
        if f in held:
            continue
        mine, theirs = yours.get(f), template.get(f)
        if mine == theirs:
            continue
        if base is None:
            out.append(FieldOutcome(f, "conflict", mine, theirs))
            continue
        was = base.get(f)
        if mine == was:
            out.append(FieldOutcome(f, "taken", mine, theirs))
        elif theirs == was:
            out.append(FieldOutcome(f, "kept", mine, theirs))
        elif f in rules:
            value = _strict(rules[f], mine, theirs)
            out.append(FieldOutcome(f, "kept" if value == mine else "taken", mine, value))
        else:
            out.append(FieldOutcome(f, "conflict", mine, theirs))
    return out


def apply(yours: Mapping[str, Any], outcomes: Iterable[FieldOutcome], choices: Mapping[str, Choice]) -> dict[str, Any]:
    """The body an update saves: yours, with each taken field and each conflict the person chose as the template's.

    Args:
        yours: The copy's newest version.
        outcomes: What `merge` listed.
        choices: Per conflicting field, `template` to take the template's value; anything else keeps yours.

    Returns:
        A new body; `yours` is not changed.
    """
    body = dict(yours)
    for o in outcomes:
        if o.outcome == "taken" or (o.outcome == "conflict" and choices.get(o.field) == "template"):
            body[o.field] = o.template
    return body


__all__ = ["Choice", "FieldOutcome", "Outcome", "Strictness", "apply", "merge"]
