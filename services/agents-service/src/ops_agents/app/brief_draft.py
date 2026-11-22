"""A first draft of an agent's brief from a short description of its job: one structured model call that proposes
a text per heading. Nothing is saved here; the console shows each heading as a change the builder accepts or skips,
and an accepted heading is an ordinary edit of the brief."""

from __future__ import annotations

from typing import Any, Protocol, TypedDict

from pydantic import BaseModel, ValidationError

from ops_service_kit.http import Json

# The headings a draft proposes, in the brief card's order. Lists hold one rule per line, as the brief stores them.
SCHEMA: Json = {
    "type": "object",
    "additionalProperties": False,
    "required": ["job", "howToAnswer", "handOff", "examples", "never"],
    "properties": {
        "job": {"type": "string"},
        "howToAnswer": {"type": "string"},
        "handOff": {"type": "array", "items": {"type": "string"}},
        "examples": {"type": "string"},
        "never": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM = (
    "You write a first draft of an operations agent's brief from the builder's description of its job. Return JSON "
    "with: job (one or two sentences: what the agent is for and what a good outcome is), howToAnswer (how it works "
    "and answers, as short paragraphs or steps), handOff (the situations where it passes the case to a person, one "
    "per item), examples (one or two short example exchanges, or empty), never (things it must never do, one per "
    "item). Mention only the tools and knowledge listed; do not invent others. Plain words, no headings."
)

# The brief's own limits (ops_agent_kernel.prompt_writer.Brief), so an accepted proposal always saves.
LIMITS = {"job": 400, "howToAnswer": 24000, "examples": 4000}
RULE, HAND_OFFS, NEVERS = 300, 10, 20


class Proposal(TypedDict):
    job: str
    howToAnswer: str
    handOff: list[str]
    examples: str
    never: list[str]


class StructuredModel(Protocol):
    async def structured(self, system: str, user: str, schema: Json, *, key: str) -> Any: ...


class _Answer(BaseModel):
    """The model's answer as read: a missing heading is empty, so one gap never loses the others."""

    job: str = ""
    howToAnswer: str = ""  # noqa: N815 - the schema's key
    handOff: list[str] = []  # noqa: N815
    examples: str = ""
    never: list[str] = []


def _rules(items: list[str], most: int) -> list[str]:
    return [r.strip()[:RULE] for r in items if r.strip()][:most]


async def draft_brief(
    model: StructuredModel, description: str, *, name: str, tools: list[str], knowledge: list[str], key: str
) -> Proposal:
    """The proposed text per heading, cut to what the brief accepts."""
    user = "\n".join(
        [
            "<draft-brief>",
            f"Agent: {name}",
            f"Tools: {', '.join(tools) or 'none'}",
            f"Knowledge: {', '.join(knowledge) or 'none'}",
            f"Description: {description}",
        ]
    )
    raw = await model.structured(SYSTEM, user, SCHEMA, key=key)
    try:
        a = _Answer.model_validate(raw)
    except ValidationError:
        a = _Answer()
    return {
        "job": a.job.strip()[: LIMITS["job"]],
        "howToAnswer": a.howToAnswer.strip()[: LIMITS["howToAnswer"]],
        "handOff": _rules(a.handOff, HAND_OFFS),
        "examples": a.examples.strip()[: LIMITS["examples"]],
        "never": _rules(a.never, NEVERS),
    }
