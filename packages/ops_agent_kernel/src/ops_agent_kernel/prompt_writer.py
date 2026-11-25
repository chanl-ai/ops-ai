"""The prompt written from an agent's brief. `head` is the stable start, stored on the agent version as its
instructions: who the agent is, its goal and how it answers. `tail` is written again before every model request and
comes last: the step of the running skill, that skill's rules, then the never rules, so nothing follows them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, cast

from pydantic import BeforeValidator, Field, model_validator

from ops_contracts.skill_run import Branch, IfNot, StepCheck
from ops_service_kit.http import In, Json
from ops_service_kit.names import name_problem, tidy

from .types import NEVER_HEADING

Rule = Annotated[str, Field(min_length=1, max_length=300)]


@dataclass(frozen=True)
class Heading:
    """One place in the prompt's order: a field of the brief (`fixed`), a section a builder adds from the menu
    (`menu`, by its id), or the place the builder's own sections go (`custom`). `label` is the heading written."""

    id: str
    label: str
    kind: Literal["fixed", "menu", "custom"]


# The order and the headings a workspace starts from; a workspace's own list (agents-service) replaces it. The
# never rules are written by `tail`, after everything else, wherever `never` stands here.
DEFAULT_HEADINGS: tuple[Heading, ...] = (
    Heading("purpose", "Purpose", "fixed"),
    Heading("goal", "Goal", "fixed"),
    Heading("personality", "Personality", "menu"),
    Heading("tone", "Tone", "menu"),
    Heading("environment", "Environment", "menu"),
    Heading("context", "Context", "menu"),
    Heading("how_to_answer", "How to answer", "fixed"),
    Heading("tool_use", "Tool use", "menu"),
    Heading("error_handling", "Error handling", "menu"),
    Heading("custom", "Custom section", "custom"),
    Heading("hand_off", "Hand off when", "fixed"),
    Heading("escalation", "Escalation wording", "menu"),
    Heading("examples", "Examples", "fixed"),
    Heading("never", NEVER_HEADING, "fixed"),
)
# The heading each default menu section is written under, for a section sent or stored without a name.
SECTION_TITLES: dict[str, str] = {h.id: h.label for h in DEFAULT_HEADINGS if h.kind == "menu"}
CUSTOM_MAX = 5
# The most a workspace may allow of a builder's own sections, and the most entries its list may hold.
CUSTOM_LIMIT = 10
HEADINGS_MAX = 40
CUSTOM_NAME_MAX = 40
# Headings no list entry carries that a custom section still may not take: the purpose is written under "Who you
# are", and "Job" and "Success checks" are kept for old versions.
SCAFFOLD_NAMES = ("Job", "Who you are", "Success checks")


def _folded(name: str) -> str:
    """A heading as compared: case, spaces around it and runs of spaces inside it do not tell two names apart."""
    return " ".join(name.split()).casefold()


def titled(data: object) -> object:
    """A section as sent or stored, with a default menu kind's title as its name when it has none; anything else as
    it is."""
    if not isinstance(data, dict):
        return data
    section = cast(Json, data)
    kind, name = section.get("kind"), section.get("name")
    if isinstance(kind, str) and kind in SECTION_TITLES and not (isinstance(name, str) and name.strip()):
        return {**section, "name": SECTION_TITLES[kind]}
    return section


def _tidied(value: object) -> object:
    return tidy(value) if isinstance(value, str) else value


class BriefSection(In):
    """A headed section a builder adds to the brief. `kind` is the id of a menu section in the workspace's list,
    written under that section's label, and the tag evals read; a `custom` section is written under its own name, is
    prompt text only and drives nothing. The save fills a menu section's name from the list."""

    kind: str = Field(min_length=1, max_length=40)
    name: Annotated[str, BeforeValidator(_tidied)] = Field(default="", max_length=200)
    text: str = Field(default="", max_length=4000)

    @model_validator(mode="before")
    @classmethod
    def _titled(cls, data: object) -> object:
        return titled(data)


def section_problem(
    sections: Sequence[BriefSection], headings: Sequence[Heading] = DEFAULT_HEADINGS, custom_max: int = CUSTOM_MAX
) -> str | None:
    """Why these sections cannot be saved under this list, in words for the builder; None when they can. A menu
    section the list hides is still accepted: an agent that already has it keeps it."""
    labels = {h.id: h.label for h in headings if h.kind == "menu"}
    menu = [s.kind for s in sections if s.kind != "custom"]
    unknown = next((k for k in menu if k not in labels), None)
    if unknown is not None:
        return f"brief.sections: {unknown} is not a section this workspace offers. Remove it."
    twice = next((k for k in menu if menu.count(k) > 1), None)
    if twice is not None:
        return f"brief.sections: {labels[twice]} is added more than once. Keep one."
    names = [s.name for s in sections if s.kind == "custom"]
    if len(names) > custom_max:
        return f"brief.sections: an agent may have at most {custom_max} sections of its own."
    reserved = {_folded(n) for n in (*SCAFFOLD_NAMES, *(h.label for h in headings))}
    seen: set[str] = set()
    for name in names:
        if name_problem(name):
            return "brief.sections: a section of your own needs a name on one line."
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
    sections: list[BriefSection] = Field(default_factory=list[BriefSection], max_length=HEADINGS_MAX + CUSTOM_LIMIT)


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


def head(name: str, brief: Brief, headings: Sequence[Heading] = DEFAULT_HEADINGS) -> str:
    """The brief as markdown sections in the list's order, each under its label: who the agent is (always under
    "Who you are"), its goal, the menu sections, how it answers, the builder's own sections where the list puts
    `custom`, when it hands off, then examples. The never rules are left to `tail`. A section saved with no text is
    left out, so a brief with no sections writes what it wrote before them. A section whose menu entry has since left
    the list is written with the builder's own, under the name it was saved with."""
    menu = {h.id for h in headings if h.kind == "menu"}
    added = {s.kind: s.text.strip() for s in brief.sections if s.kind in menu}
    own = [s for s in brief.sections if s.kind not in menu and s.text.strip()]
    hand_off = [r.strip() for r in brief.hand_off if r.strip()]
    fields = {
        "goal": brief.goal.strip(),
        "how_to_answer": brief.how_to_answer.strip(),
        "hand_off": "\n".join(f"- {r}" for r in hand_off),
        "examples": brief.examples.strip(),
    }
    sections: list[str] = []
    for h in headings:
        if h.id == "purpose":
            sections.append(f"# Who you are\nYou are {name}.\nYour job: {brief.purpose.strip()}")
        elif h.kind == "custom":
            sections += [f"# {s.name.strip()}\n{s.text.strip()}" for s in own]
        elif text := (added.get(h.id) if h.kind == "menu" else fields.get(h.id)):
            sections.append(f"# {h.label}\n{text}")
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


def tail(now: Now | None, never: Sequence[str], heading: str = NEVER_HEADING) -> str:
    """What follows everything else in the prompt, the never rules last under `heading`; empty when no skill is
    running and there is no never rule."""
    sections: list[str] = []
    if now is not None:
        sections.append(_step(now))
        if now.rules.strip():
            sections.append(f"# Rules for this skill\n{now.rules.strip()}")
    rules = [r.strip() for r in never if r.strip()]
    if rules:
        sections.append(f"# {heading}\n" + "\n".join(f"- {r}" for r in rules))
    return "\n\n".join(sections)
