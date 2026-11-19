"""Skills in a turn (spec 11 5.3): the index of on-match skills in the system prompt, always-on bodies after the
agent's instructions, and the `load_skill` built-in that returns an on-match body. A load past either cap (two
on-match skills a turn, 6,000 tokens of bodies a turn after always-on bodies) is refused and the turn goes on without
it, as is a part over its own budget. A skill with parts is offered as one entry per part (`<skill>/<part>`); a part
picked from the / menu arrives loaded and counts against the caps like a load. A skill adds instructions and, while
loaded, guardrails; it never adds a tool.
"""

from __future__ import annotations

from collections.abc import Sequence

from ops_service_kit.http import Json, JsonList

from .events import SkillLoaded
from .types import Guardrail, LoadedSkill, Skill, ToolGrant

NAME = "load_skill"
MAX_PER_TURN = 2
# On-match bodies loaded in one reply. Always-on bodies have their own budget (ALWAYS_BUDGET, checked when they are
# attached), so they can never use up the room on-match loads need.
TOKEN_BUDGET = 6000
ALWAYS_BUDGET = 2000
MATCHED_MAX = 200
ALWAYS = "Always on"


def grant(skills: list[Skill], stepped: Sequence[Skill] = ()) -> ToolGrant | None:
    """The built-in, offered when the agent pins an on-match skill without steps or holds a skill with steps
    (`stepped`); its slug argument is one of theirs. A skill with steps is never loaded as text: loading it starts it
    at its first step, as switch_skill does (step_tools.py)."""
    slugs: JsonList = [s.slug for s in skills if s.loading == "on_match" and s.program is None]
    slugs += [s.slug for s in stepped if s.slug not in slugs]
    if not slugs:
        return None
    does = (
        "Loads one of your skills by its slug when the task matches its use-when line. Follow the steps and rules "
        "it returns for the rest of this reply."
    )
    if stepped:
        does += " A skill that runs step by step starts at its first step instead."
    return ToolGrant(
        NAME,
        "platform",
        does,
        "read",
        {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "enum": slugs},
                "part": {"type": "string", "description": "The part to load, for a slug of the form <skill>/<part>"},
                "matched": {"type": "string", "description": "The words in the request that match the use-when line"},
            },
            "required": ["slug"],
        },
    )


def prompt(skills: list[Skill]) -> str:
    """What the system prompt adds: the always-on bodies in pin order, the index of on-match skills to load, then the
    index of skills with steps to start."""
    parts = [f"## {s.name}\n\n{s.instructions}" for s in skills if s.loading == "always" and s.program is None]
    index = [f"- {s.slug}: {s.use_when}" for s in skills if s.loading == "on_match" and s.program is None]
    if index:
        parts.append(
            "## Skills you can load\n\nWhen a request matches one of these, call load_skill with its slug before "
            "answering, then follow what it returns.\n" + "\n".join(index)
        )
    started = [
        f"- {s.slug}: {s.use_when}"
        + (f" Not when: {s.program.not_when}" if s.program.not_when else "")
        + (f" Its steps call: {', '.join(sorted(tools))}." if (tools := s.program.targets()) else "")
        for s in skills
        if s.program is not None
    ]
    if started:
        parts.append(
            "## Skills you can start\n\nThese run one step at a time. When a request matches one, call switch_skill "
            "with its slug before answering and before calling any tool its steps call; you are then given its "
            "current step.\n" + "\n".join(started)
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


def loaded_entry(skill: Skill, matched: str, inputs: dict[str, str] | None = None) -> LoadedSkill:
    """`matched` comes from the model: kept to one plain line of at most 200 characters before it is journalled. A
    part and a picked part's inputs are kept only when there are any."""
    clean = " ".join("".join(ch if ch.isprintable() else " " for ch in matched).split())[:MATCHED_MAX]
    entry: LoadedSkill = {
        "skillId": skill.skill_id,
        "name": skill.name,
        "version": skill.version,
        "matched": clean or skill.use_when[:MATCHED_MAX],
    }
    if skill.part:
        entry["part"] = skill.part
    if inputs:
        entry["inputs"] = inputs
    return entry


def event(entry: LoadedSkill, how: str) -> SkillLoaded:
    """The journal event for one entry of the turn's loads, with how it entered the reply."""
    return SkillLoaded(
        entry["skillId"], entry["version"], entry["name"], entry["matched"], entry.get("part"), how, entry.get("inputs")
    )


def same(skill: Skill, entry: LoadedSkill | Json) -> bool:
    """Whether a journalled entry names this skill, and this part of it."""
    return skill.skill_id == entry.get("skillId") and skill.part == (entry.get("part") or "")


def load(
    skills: list[Skill], loaded: list[Skill], slug: str, carried: list[Skill] | None = None
) -> tuple[Skill | None, str | None]:
    """The skill to load for `slug`, or why the load is refused. `carried` skills, loaded by an earlier turn, are
    already loaded but count against neither of this turn's caps."""
    skill = next((s for s in skills if s.slug == slug and s.loading == "on_match" and s.program is None), None)
    if skill is None:
        return None, f"No skill named {slug} is attached to this agent."
    if skill in loaded:
        return skill, None
    if skill.budget and skill.tokens > skill.budget:
        return None, f"{skill.name} is over its own {skill.budget}-token budget; go on without it."
    on_match = [s for s in loaded if s.loading == "on_match" and s not in (carried or [])]
    if len(on_match) >= MAX_PER_TURN:
        return None, f"At most {MAX_PER_TURN} skills load in one reply; go on without {skill.name}."
    used = sum(s.tokens for s in on_match)
    if used + skill.tokens > TOKEN_BUDGET:
        return None, f"{skill.name} would pass the {TOKEN_BUDGET}-token skill budget for one reply; go on without it."
    return skill, None
