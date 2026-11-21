"""The prompt written from an agent's brief. `head` is the stable start, stored on the agent version as its
instructions: who the agent is, its goal and how it answers. `tail` is written again before every model request and
comes last: the step of the running skill, that skill's rules, then the never rules, so nothing follows them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

from ops_contracts.skill_run import Branch, IfNot, StepCheck
from ops_service_kit.http import In

Rule = Annotated[str, Field(min_length=1, max_length=300)]


class Brief(In):
    """What a builder writes instead of one block of instructions. Persona, tone and glossary are text inside
    `how_to_answer`. `success` is kept for grading and is never sent to the model."""

    purpose: str = Field(min_length=1, max_length=400)
    goal: str = Field(default="", max_length=600)
    how_to_answer: str = Field(default="", max_length=24000)
    never: list[Rule] = Field(default_factory=list[Rule], max_length=20)
    success: list[Rule] = Field(default_factory=list[Rule], max_length=8)


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
    sections = [f"# Who you are\nYou are {name}.\nYour job: {brief.purpose.strip()}"]
    if brief.goal.strip():
        sections.append(f"# Goal\n{brief.goal.strip()}")
    if brief.how_to_answer.strip():
        sections.append(f"# How to answer\n{brief.how_to_answer.strip()}")
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
