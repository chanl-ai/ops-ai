"""Skills in a turn (spec 11 5.3): the index of on-match skills in the system prompt, always-on bodies after the
agent's instructions, and the `load_skill` built-in that returns an on-match body. A load past either cap (two
on-match skills a turn, 6,000 tokens of bodies a turn after always-on bodies) is refused and the turn goes on without
it. A skill adds instructions and, while loaded, guardrails; it never adds a tool.
"""

from __future__ import annotations

from typing import Any

from .types import Guardrail, Skill, ToolGrant

NAME = "load_skill"
MAX_PER_TURN = 2
# On-match bodies loaded in one reply. Always-on bodies have their own budget (ALWAYS_BUDGET, checked when they are
# attached), so they can never use up the room on-match loads need.
TOKEN_BUDGET = 6000
ALWAYS_BUDGET = 2000
MATCHED_MAX = 200
ALWAYS = "Always on"


def grant(skills: list[Skill]) -> ToolGrant | None:
    """The built-in, offered only when the agent pins an on-match skill; its slug argument is one of theirs."""
    slugs = [s.slug for s in skills if s.loading == "on_match"]
    if not slugs:
        return None
    return ToolGrant(
        NAME,
        "platform",
        "Loads one of your skills by its slug when the task matches its use-when line. Follow the steps and rules "
        "it returns for the rest of this reply.",
        "read",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "enum": slugs},
                "matched": {"type": "string", "description": "The words in the request that match the use-when line"},
            },
            "required": ["slug"],
        },
    )


def prompt(skills: list[Skill]) -> str:
    """What the system prompt adds: the always-on bodies in pin order, then the index of on-match skills."""
    parts = [f"## {s.name}\n\n{s.instructions}" for s in skills if s.loading == "always"]
    index = [f"- {s.slug}: {s.use_when}" for s in skills if s.loading == "on_match"]
    if index:
        parts.append(
            "## Skills you can load\n\nWhen a request matches one of these, call load_skill with its slug before "
            "answering, then follow what it returns.\n" + "\n".join(index)
        )
    return "\n\n".join(parts)


def guardrails_of(skill: Skill) -> list[Guardrail]:
    """A loaded skill's guardrail lines, as blocked-topic rules for the same classifier. Each topic is listed with the
    skill's own use-when as what it does not cover: listed bare, a real model read a hardship question as the hardship
    skill's "promising a deferral" topic and refused the very request the skill is for (seed-walk check a)."""
    if not skill.guardrails:
        return []
    # A skill's guardrail never holds the answer: there is no setting for it, so it streams and is replaced on a hit.
    message = skill.refusal.strip() or f"I can't help with that here: the {skill.name} skill does not allow it."
    use_when = skill.use_when.strip().rstrip(".")
    scope = f"only this. Not: {use_when}, which the {skill.name} skill handles."
    scopes = tuple((t, scope) for t in skill.guardrails) if use_when else ()
    return [Guardrail(skill.skill_id, skill.version, f"{skill.name} (skill)", skill.guardrails, message, scopes)]


def loaded_entry(skill: Skill, matched: str) -> dict[str, Any]:
    """`matched` comes from the model: kept to one plain line of at most 200 characters before it is journalled."""
    clean = " ".join("".join(ch if ch.isprintable() else " " for ch in matched).split())[:MATCHED_MAX]
    return {
        "skillId": skill.skill_id,
        "name": skill.name,
        "version": skill.version,
        "matched": clean or skill.use_when[:MATCHED_MAX],
    }


def load(skills: list[Skill], loaded: list[Skill], slug: str) -> tuple[Skill | None, str | None]:
    """The skill to load for `slug`, or why the load is refused."""
    skill = next((s for s in skills if s.slug == slug and s.loading == "on_match"), None)
    if skill is None:
        return None, f"No skill named {slug} is attached to this agent."
    if skill in loaded:
        return skill, None
    on_match = [s for s in loaded if s.loading == "on_match"]
    if len(on_match) >= MAX_PER_TURN:
        return None, f"At most {MAX_PER_TURN} skills load in one reply; go on without {skill.name}."
    used = sum(s.tokens for s in on_match)
    if used + skill.tokens > TOKEN_BUDGET:
        return None, f"{skill.name} would pass the {TOKEN_BUDGET}-token skill budget for one reply; go on without it."
    return skill, None
