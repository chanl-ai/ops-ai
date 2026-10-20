"""Blocked-topic guardrails (c-063): one classification call, with structured output validated against a schema whose
topic is one of the pinned topics or "none". Through models-service the call runs on its own alias, `guardrail-check`,
so an operator can give the check a stronger model than the answering one; while that alias is not bound it runs on
the turn's own model, so nothing changes without the binding. It runs on the person's message before
the answer and on the answer after it (kernel.py). A call that fails, or returns anything outside the schema, raises
GuardrailUnavailable: the turn then fails closed rather than answering unchecked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.output import StructuredDict

from .aliases import preferred
from .ports import ModelSource
from .types import Guardrail

NONE = "none"
GUARD_ALIAS = "guardrail-check"
INSTRUCTIONS = (
    "You check one message against a list of blocked topics. Answer with the blocked topic the message asks about or "
    'discusses, exactly as listed, or "none" when it touches none of them. Judge the meaning, not single words. A '
    "topic followed by a colon says what it covers and what it does not; a message the topic does not cover is "
    '"none" for that topic.'
)


class GuardrailUnavailable(Exception):
    """The check could not run or returned something it cannot vouch for."""


@dataclass(frozen=True)
class Hit:
    rule: Guardrail
    topic: str


def model_for(source: ModelSource | None, turn_model: Model) -> Model:
    """The model the check runs on: `guardrail-check` through models-service, or the turn's model while that alias does
    not exist. Only models-service's "no such alias" falls back; any other failure fails the turn closed."""
    return preferred(source, GUARD_ALIAS, turn_model)


def _schema(topics: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"topic": {"type": "string", "enum": [*topics, NONE]}, "reason": {"type": "string"}},
        "required": ["topic"],
    }


def _labels(rules: list[Guardrail]) -> list[tuple[str, Guardrail, str, str | None]]:
    """Each rule's topics as the classifier lists them: (label, rule, topic, scope). A topic two rules share with the
    same scope is listed once; with different scopes, once per rule, labelled with the rule's name, so one rule's scope
    (a skill's "Not: hardship") never narrows another's (a team's rule on the same topic)."""
    scoped = [(r, t, dict(r.scopes).get(t) or None) for r in rules for t in r.topics]
    scopes_of: dict[str, set[str | None]] = {}
    for _, t, s in scoped:
        scopes_of.setdefault(t, set()).add(s)
    out: dict[str, tuple[str, Guardrail, str, str | None]] = {}
    for r, t, s in scoped:
        label = t if len(scopes_of[t]) == 1 else f"{t} ({r.name})"
        out.setdefault(label, (label, r, t, s))
    return list(out.values())


async def check(model: Model, rules: list[Guardrail], text: str) -> Hit | None:
    """The pinned rule `text` falls under, or None when it touches no blocked topic."""
    labels = _labels(rules)
    schema = _schema([label for label, _, _, _ in labels])
    agent = Agent[None, Any](
        model,
        deps_type=type(None),
        output_type=StructuredDict(schema, name="final_result"),
        instructions=INSTRUCTIONS,
        retries=0,
    )
    # A bare label is read broadly ("investment advice" swallowed comparing the bank's own savings products), so a
    # topic's scope is listed beside it, for its own rule only.
    listed = "\n".join(f"- {label}: {scope}" if scope else f"- {label}" for label, _, _, scope in labels)
    try:
        result = await agent.run(f"Blocked topics:\n{listed}\n\nMessage:\n{text}")
    except Exception as e:  # any failure of the call is a check that did not run
        raise GuardrailUnavailable(f"{type(e).__name__}: {e}") from e
    found: list[Any] = list(Draft202012Validator(schema).iter_errors(result.output))  # pyright: ignore[reportUnknownMemberType]
    if found:
        raise GuardrailUnavailable(f"The check returned {result.output!r}: {found[0].message}")
    label = str(result.output["topic"])
    if label == NONE:
        return None
    return next(Hit(r, topic) for found, r, topic, _ in labels if found == label)
