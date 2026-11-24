"""The prompt written from an agent's brief. `head` is the stable start, stored on the agent version as its
instructions: who the agent is, its goal and how it answers. `tail` is written again before every model request and
comes last: the step of the running skill, that skill's rules, then the never rules, so nothing follows them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, cast

from pydantic import Field, model_validator

from ops_contracts.skill_run import Branch, IfNot, StepCheck
from ops_service_kit.http import In
from ops_service_kit.names import Name

Rule = Annotated[str, Field(min_length=1, max_length=300)]

SectionKind = Literal[
    "personality", "tone", "environment", "context", "tool_use", "error_handling", "escalation", "custom"
]
# The heading each section from the menu is written under; a custom section is written under its own name.
SECTION_TITLES: dict[str, str] = {
    "personality": "Personality",
    "tone": "Tone",
    "environment": "Environment",
    "context": "Context",
    "tool_use": "Tool use",
    "error_handling": "Error handling",
    "escalation": "Escalation wording",
}
CUSTOM_MAX = 5
CUSTOM_NAME_MAX = 40
# Headings a custom section may not take, because the brief writes them itself or keeps them for old versions.
RESERVED_NAMES = (
    "Job",
    "Purpose",
    "Who you are",
    "Goal",
    "How to answer",
    "Hand off when",
    "Examples",
    "Never",
    "Success checks",
    *SECTION_TITLES.values(),
)


def _folded(name: str) -> str:
    """A heading as compared: case, spaces around it and runs of spaces inside it do not tell two names apart."""
    return " ".join(name.split()).casefold()


def titled(data: object) -> object:
    """A section as sent or stored, with a menu kind's fixed title as its name; anything else as it is."""
    if not isinstance(data, dict):
        return data
    section = cast(dict[str, object], data)
    kind = section.get("kind")
    return {**section, "name": SECTION_TITLES[kind]} if isinstance(kind, str) and kind in SECTION_TITLES else section


class BriefSection(In):
    """A headed section a builder adds to the brief. A menu kind is written under its fixed title, whatever name is
    sent; `kind` is the tag evals read. A custom section is prompt text only and drives nothing."""

    kind: SectionKind
    # A menu kind's title is filled before this is read, so only a custom section can be refused here as blank.
    name: Name
    text: str = Field(default="", max_length=4000)

    @model_validator(mode="before")
    @classmethod
    def _titled(cls, data: object) -> object:
        return titled(data)


def section_problem(sections: Sequence[BriefSection]) -> str | None:
    """Why these sections cannot be saved, in words for the builder; None when they can."""
    menu = [s.kind for s in sections if s.kind != "custom"]
    twice = next((k for k in menu if menu.count(k) > 1), None)
    if twice is not None:
        return f"brief.sections: {SECTION_TITLES[twice]} is added more than once. Keep one."
    names = [s.name for s in sections if s.kind == "custom"]
    if len(names) > CUSTOM_MAX:
        return f"brief.sections: an agent may have at most {CUSTOM_MAX} sections of its own."
    reserved = {_folded(n) for n in RESERVED_NAMES}
    seen: set[str] = set()
    for name in names:
        if len(name) > CUSTOM_NAME_MAX:
            return f"brief.sections: a section's name is at most {CUSTOM_NAME_MAX} characters."
        if _folded(name) in reserved:
            return f"brief.sections: {name} is a heading the brief already has. Pick another name."
        if _folded(name) in seen:
            return f"brief.sections: two sections are named {name}. Give each its own name."
        seen.add(_folded(name))
    return None


class Brief(In):
    """What a builder writes instead of one block of instructions. Personality, tone and the like are `sections`
    the builder adds; text already inside `how_to_answer` stays there. `purpose` is the Job; `goal` is kept on agents
    that already have one and is not asked for on new ones. `success` is kept readable on old versions and is never
    sent to the model. `hand_off`, `examples` and `sections` default to empty, so a version stored before them reads
    and runs as it did."""

    purpose: str = Field(min_length=1, max_length=400)
    goal: str = Field(default="", max_length=600)
    how_to_answer: str = Field(default="", max_length=24000)
    hand_off: list[Rule] = Field(default_factory=list[Rule], max_length=10)
    examples: str = Field(default="", max_length=4000)
    never: list[Rule] = Field(default_factory=list[Rule], max_length=20)
    success: list[Rule] = Field(default_factory=list[Rule], max_length=8)
    # Headed sections added from the menu or written by the builder; checked on save by `section_problem`.
    sections: list[BriefSection] = Field(
        default_factory=list[BriefSection], max_length=len(SECTION_TITLES) + CUSTOM_MAX
    )


class Patterns(In):
    """How the agent's turn runs: how hard the model thinks, and whether reads may run side by side."""

    thinking: Literal["default", "low", "medium", "high"] = "default"
    parallel_reads: bool = True


@dataclass(frozen=True)
class Now:
    """The step the running skill is on, in the words the model is given."""

    skill: str
    step: int
    of: int
    do: str
    # The tool or skill the step runs, by the name the model knows it under.
    use: str | None = None
    check: StepCheck | None = None
    if_not: IfNot | None = None
    # The path the step's text wrote (`if ...:`), decided once the step is done.
    branch: Branch | None = None
    # The skill whose step started this one, when this is a sub-skill.
    inside: str | None = None
    rules: str = ""
    # Every step has passed and the skill waits for its results: the names it must be ended with.
    owes: tuple[str, ...] | None = None


def head(name: str, brief: Brief) -> str:
    """The brief as markdown sections: who the agent is, its goal, how it sounds and where it works, how it answers
    and uses its tools, the builder's own sections, when and how it hands off, then examples. A section saved with no
    text is left out, so a brief with no sections writes what it wrote before them."""
    added = {s.kind: s.text.strip() for s in brief.sections if s.kind != "custom"}

    def menu(*kinds: str) -> list[str]:
        return [f"# {SECTION_TITLES[k]}\n{added[k]}" for k in kinds if added.get(k)]

    sections = [f"# Who you are\nYou are {name}.\nYour job: {brief.purpose.strip()}"]
    if brief.goal.strip():
        sections.append(f"# Goal\n{brief.goal.strip()}")
    sections += menu("personality", "tone", "environment", "context")
    if brief.how_to_answer.strip():
        sections.append(f"# How to answer\n{brief.how_to_answer.strip()}")
    sections += menu("tool_use", "error_handling")
    sections += [
        f"# {s.name.strip()}\n{s.text.strip()}" for s in brief.sections if s.kind == "custom" and s.text.strip()
    ]
    hand_off = [r.strip() for r in brief.hand_off if r.strip()]
    if hand_off:
        sections.append("# Hand off when\n" + "\n".join(f"- {r}" for r in hand_off))
    sections += menu("escalation")
    if brief.examples.strip():
        sections.append(f"# Examples\n{brief.examples.strip()}")
    return "\n\n".join(sections)


def _if_not(rule: IfNot | None) -> str:
    rule = rule or IfNot()
    if rule.action == "goto":
        return f"go to step {rule.step}."
    if rule.action == "exit":
        return f"the skill ends as {rule.exit}."
    again = "once more" if rule.retries == 1 else f"up to {rule.retries} more times"
    if rule.retries == 0:
        return "the skill ends as failed."
    return f"ask the person for what is missing and try {again}; after that the skill ends as failed."


def _step(now: Now) -> str:
    where = f", inside {now.inside}" if now.inside else ""
    lines = [f"# Now: {now.skill}, step {now.step} of {now.of}{where}"]
    if now.owes is not None:
        results = f" and these results: {', '.join(now.owes)}" if now.owes else ""
        lines.append(f"Every step is done. Call exit with the name done{results}.")
        return "\n".join(lines)
    lines.append(now.do)
    if now.use:
        lines.append(f"Use: {now.use}")
    if now.branch is not None:
        if now.use:
            lines.append(f"Done when: {now.use} has run.")
        else:
            lines.append("Done when: you have done it; then call step_done.")
        if now.branch.test.by == "rule":
            lines.append("Then: a rule on the result picks the next step; do not judge it yourself.")
        else:
            lines.append(
                f"Then: a judge decides whether {now.branch.test.text} and picks the next step; do not judge it "
                "yourself."
            )
        lines.append("Do only this step. If the person now asks for something else, call switch_skill or exit.")
        return "\n".join(lines)
    if now.check is not None and now.check.by == "rule":
        lines.append("Done when: the check runs on the tool result; do not judge it yourself.")
    elif now.check is not None and now.use:
        lines.append(f"Done when: a judge finds this holds on the tool result: {now.check.text}")
    elif now.check is not None:
        lines.append(f"Done when: {now.check.text} Call step_done once it is done; a judge decides it from this reply.")
    elif now.use:
        lines.append(f"Done when: {now.use} has run.")
    else:
        lines.append("Done when: you have done it; then call step_done.")
    if now.check is not None or now.use:
        lines.append(f"If not: {_if_not(now.if_not)}")
    lines.append("Do only this step. If the person now asks for something else, call switch_skill or exit.")
    return "\n".join(lines)


def tail(now: Now | None, never: Sequence[str]) -> str:
    """What follows everything else in the prompt; empty when no skill is running and there is no never rule."""
    sections: list[str] = []
    if now is not None:
        sections.append(_step(now))
        if now.rules.strip():
            sections.append(f"# Rules for this skill\n{now.rules.strip()}")
    rules = [r.strip() for r in never if r.strip()]
    if rules:
        sections.append("# Never\n" + "\n".join(f"- {r}" for r in rules))
    return "\n\n".join(sections)
