"""Skills with steps: the program a skill version stores, the problems that stop one from running, and how the
record of a running skill moves from step to step.

The models live in `ops_contracts.skill_run`, because the record carries the program of the version that started and
the console and SDKs read it; they are re-exported here, where the kernel's rules for them are.
"""

from __future__ import annotations

from dataclasses import dataclass

from ops_contracts.skill_run import (
    BUILT_IN_EXITS,
    REF_TOKEN,
    EndedSkill,
    IfNot,
    Ref,
    ReturnField,
    RunningSkill,
    SkillProgram,
    SkillRunState,
    SkillStep,
    StepCheck,
    StepResult,
    SubRun,
)

from . import expr

__all__ = [
    "BUILT_IN_EXITS",
    "REF_TOKEN",
    "EndedSkill",
    "IfNot",
    "Ref",
    "ReturnField",
    "RunningSkill",
    "SkillProgram",
    "SkillRunState",
    "SkillStep",
    "StepCheck",
    "StepProblem",
    "StepResult",
    "SubRun",
    "problems",
]


@dataclass(frozen=True)
class StepProblem:
    """Why a program cannot run: a code a caller can act on, the step it is in (from 1) when it is in one, and a
    sentence for the person."""

    kind: str
    step: int | None
    message: str


def problems(program: SkillProgram, *, has_parts: bool = False, always_on: bool = False) -> list[StepProblem]:
    """What stops `program` from running, by its own shape. Whether a skill a step runs exists, and whether skills
    run each other in a circle, needs the team's skills and is checked by the caller."""
    found: list[StepProblem] = []
    count = len(program.steps)
    if not count:
        if program.returns or program.exit or program.success:
            found.append(StepProblem("no_steps", None, "Results, exits and success checks need at least one step."))
        return found
    if has_parts:
        found.append(StepProblem("steps_and_parts", None, "A skill has steps or parts, not both."))
    if always_on:
        found.append(
            StepProblem("steps_always_on", None, "A skill with steps is started when needed; it cannot be always on.")
        )
    for n, step in enumerate(program.steps, start=1):
        if step.use is not None and step.use.kind == "knowledge":
            found.append(
                StepProblem(
                    "bad_use", n, "A step runs a tool, a skill, an agent or a workflow; mention knowledge in its text."
                )
            )
        if step.check is not None:
            try:
                expr.kind_of(step.check.text)
            except expr.CheckError as e:
                found.append(
                    StepProblem("bad_check", n, f"Step {n}'s check reads as a rule but is not a valid one. {e}")
                )
        if (if_not := step.if_not) is None:
            continue
        if if_not.action == "goto" and (if_not.step is None or if_not.step > count or if_not.step == n):
            found.append(StepProblem("bad_goto", n, f"Step {n} goes to a step that is not another step of this skill."))
        if if_not.action == "exit" and if_not.exit not in program.exits():
            found.append(
                StepProblem("unknown_exit", n, f"Step {n} ends with {if_not.exit}, which this skill does not list.")
            )
    return found


def judged(program: SkillProgram) -> SkillProgram:
    """`program` with each check marked by who judges it: a valid rule runs in code, a sentence is confirmed by the
    model. A value a client sent for `by` is replaced. Call `problems` first: a mistyped rule raises here."""
    steps = [
        s.model_copy(update={"check": s.check.model_copy(update={"by": expr.kind_of(s.check.text)})})
        if s.check is not None
        else s
        for s in program.steps
    ]
    return program.model_copy(update={"steps": steps})
