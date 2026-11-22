"""The paths a skill's steps can take, for trying one: each `if` either holds or does not, and each way leads through
the steps after it to an exit or the last step. A path lists its steps in order with the way each `if` went, so a try
runs exactly the tools on it. Jumps go forward only (`Jump`), so every path ends; a step reached twice ends the path
rather than looping."""

from __future__ import annotations

from dataclasses import dataclass, field

from ops_agent_kernel.steps import Jump, SkillProgram

# Enough for every path of a skill a person writes; past it the list says so rather than growing without end.
MAX_PATHS = 16


@dataclass(frozen=True)
class PathStep:
    number: int
    do: str
    # The tool the step runs; None for a step the model does itself or one that runs a skill.
    tool: str | None
    # The step's `if` and which way this path takes it; None on a step with no `if`.
    test: str | None = None
    holds: bool | None = None


@dataclass(frozen=True)
class SkillPath:
    id: str
    label: str
    # Where the path ends: "done" past the last step, else the exit it reaches.
    ends: str
    steps: list[PathStep] = field(default_factory=list[PathStep])


def _label(steps: list[PathStep]) -> str:
    ways = [f"{s.test}: {'yes' if s.holds else 'no'}" for s in steps if s.test is not None]
    return " · ".join(ways) if ways else "Every step"


def paths(program: SkillProgram) -> tuple[list[SkillPath], bool]:
    """Every path through `program`, and whether there were more than MAX_PATHS (the list then holds the first)."""
    found: list[SkillPath] = []
    more = False

    def emit(taken: list[PathStep], ends: str) -> None:
        nonlocal more
        if len(found) >= MAX_PATHS:
            more = True
            return
        ways = "".join("y" if s.holds else "n" for s in taken if s.test is not None)
        found.append(SkillPath(id=f"p{ways}", label=_label(taken), ends=ends, steps=taken))

    def go(to: Jump | None, after: int, taken: list[PathStep]) -> None:
        if to is not None and to.exit is not None:
            emit(taken, to.exit)
            return
        walk(to.step if to is not None and to.step is not None else after + 1, taken)

    def walk(n: int, taken: list[PathStep]) -> None:
        if n > len(program.steps):
            emit(taken, "done")
            return
        if any(s.number == n for s in taken):
            emit(taken, "loops")
            return
        step = program.steps[n - 1]
        tool = step.use.tool_name if step.use is not None else None
        if step.branch is None:
            go(step.next, n, [*taken, PathStep(n, step.do, tool)])
            return
        test = step.branch.test.text
        go(step.next, n, [*taken, PathStep(n, step.do, tool, test, True)])
        go(step.branch.otherwise, n, [*taken, PathStep(n, step.do, tool, test, False)])

    if program.steps:
        walk(1, [])
    return found, more
