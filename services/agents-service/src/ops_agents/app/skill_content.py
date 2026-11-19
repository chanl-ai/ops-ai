"""A skill's steps when it is saved and when a publish is asked for. A save refuses a program that could not run
(a mistyped rule, a jump to nowhere, steps beside parts, a sub-skill that is missing or runs a skill itself), marks
each check by who judges it, and adds what the steps name to the skill's own tools and knowledge bases. A publish
check lists, with the step it is in, every tool or skill a step names that the team no longer offers.

It reads the team's skills through `TeamSkills` and is given the tools the directory offers, never a `Runtime`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

from pydantic import ValidationError

from ops_agent_kernel import steps
from ops_agent_kernel.steps import Ref, SkillProgram
from ops_service_kit.errors import ValidationFailed
from ops_service_kit.http import Json

# The keys a skill version stores its program under, beside `instructions`; each is written only when set.
KEYS = ("notWhen", "steps", "exit", "returns", "success")


@dataclass(frozen=True)
class KnownSkill:
    """What a save needs to know of a skill a step runs: whose it is, whether it can be run, and the skills its own
    published steps run."""

    id: str
    name: str
    team_id: str
    published: bool
    deprecated: bool
    runs: frozenset[str]


class TeamSkills(Protocol):
    async def skill(self, skill_id: str) -> KnownSkill | None:
        """The skill, when the caller's team can see it."""
        ...

    async def running(self, skill_id: str, team_id: str) -> list[str]:
        """The names of the team's published skills whose steps run `skill_id`."""
        ...


class Position(TypedDict):
    """Where in a skill or an agent a problem is: the field, and the step (from 1) or list index when it has one."""

    field: str
    step: int | None
    index: int | None


class Problem(TypedDict):
    """One thing that blocks a publish, in a form a page can point at."""

    kind: Literal[
        "missing_field",
        "missing_reference",
        "unavailable_reference",
        "bad_step",
        "bad_check",
        "bad_exit",
        "sub_skill_not_held",
        "prompt_rule_in_text",
        "review_open",
        "already_published",
        "deprecated",
        "too_long",
    ]
    id: str | None
    position: Position | None
    message: str


def runs_of(content: Json) -> frozenset[str]:
    """The ids of the skills a stored version's steps run."""
    program = program_of(content)
    if program is None:
        return frozenset()
    return frozenset(s.use.id for s in program.steps if s.use is not None and s.use.kind == "skill")


def program_of(content: Json) -> SkillProgram | None:
    """A stored version's program, each step with the tool it runs (`steps.wired`); None for a skill without steps.
    Stored content was checked when it was saved."""
    if not content.get("steps"):
        return None
    return steps.wired(SkillProgram.model_validate({k: content[k] for k in KEYS if k in content}))


def _refused(problem: steps.StepProblem) -> ValidationFailed:
    return ValidationFailed(
        problem.message, code=problem.kind, details={"step": problem.step} if problem.step is not None else None
    )


async def checked(
    fields: Json, *, skill_id: str | None, team_id: str, has_parts: bool, always_on: bool, skills: TeamSkills
) -> SkillProgram | None:
    """The program a save sends, checked and with each check marked `rule` or `model`; None when it sends none.
    Refused (400, with the step) when it could not run."""
    given = {k: fields[k] for k in KEYS if fields.get(k)}
    if not given:
        return None
    try:
        program = SkillProgram.model_validate(given)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise ValidationFailed(f"{where}: {first['msg']}") from e
    if found := steps.problems(program, has_parts=has_parts, always_on=always_on):
        raise _refused(found[0])
    program = steps.judged(program)
    sub_steps = [(n, s.use.id) for n, s in enumerate(program.steps, start=1) if s.use and s.use.kind == "skill"]
    for n, target_id in sub_steps:
        if target_id == skill_id:
            raise _refused(steps.StepProblem("sub_skill_cycle", n, f"Step {n} runs this skill itself."))
        target = await skills.skill(target_id)
        if target is None or target.team_id != team_id or not target.published or target.deprecated:
            raise ValidationFailed(
                f"Step {n} runs {target_id}, which is not a published skill of this team.",
                code="unknown_reference",
                details={"step": n, "id": f"skill:{target_id}"},
            )
        if skill_id is not None and skill_id in target.runs:
            raise _refused(
                steps.StepProblem("sub_skill_cycle", n, f"Step {n} runs {target.name}, which runs this skill.")
            )
        if target.runs:
            raise _refused(
                steps.StepProblem(
                    "sub_skill_depth", n, f"Step {n} runs {target.name}, whose own steps run a skill; one level only."
                )
            )
    if sub_steps and skill_id is not None and (parents := await skills.running(skill_id, team_id)):
        raise _refused(
            steps.StepProblem(
                "sub_skill_depth",
                sub_steps[0][0],
                f"{parents[0]} runs this skill as a step, so this skill's own steps cannot run a skill.",
            )
        )
    return program


def stored(program: SkillProgram | None) -> Json:
    """The keys a version stores for `program`: each only when set, so a skill without steps stores none of them and
    keeps the digest it had."""
    if program is None:
        return {}
    wire: Json = program.model_dump(mode="json", by_alias=True, exclude_none=True)
    return {k: wire[k] for k in KEYS if wire.get(k)}


def _named(program: SkillProgram) -> list[tuple[Position, Ref]]:
    """Every reference the program names, with where: a step's `use`, and the `@kind:id` tokens in its text, its
    check and the not-when line."""
    found: list[tuple[Position, Ref]] = []
    for ref in Ref.found_in(program.not_when):
        found.append(({"field": "notWhen", "step": None, "index": None}, ref))
    for n, step in enumerate(program.steps, start=1):
        at: Position = {"field": "steps", "step": n, "index": None}
        refs = [step.use] if step.use is not None else []
        refs += Ref.found_in(step.do)
        refs += Ref.found_in(step.check.text) if step.check is not None else []
        seen: set[str] = set()
        for ref in refs:
            if ref.token not in seen:
                seen.add(ref.token)
                found.append((at, ref))
    return found


def scope(program: SkillProgram | None) -> tuple[list[str], list[str]]:
    """The tools (by the id each is granted under) and the knowledge bases the program names: a save adds them to
    the skill's own lists, which is the scope an agent must hold to attach it."""
    if program is None:
        return [], []
    refs = [ref for _, ref in _named(program)]
    tools = [name for ref in refs if (name := ref.tool_name) is not None]
    bases = [ref.id for ref in refs if ref.kind == "knowledge"]
    return list(dict.fromkeys(tools)), list(dict.fromkeys(bases))


async def publish_problems(
    content: Json, offered: set[str] | None, *, team_id: str, skills: TeamSkills
) -> list[Problem]:
    """What in the skill's steps blocks a publish. `offered` is the ids the tools directory offers now; None when it
    could not answer, which blocks the publish with one problem, since nothing can be checked."""
    program = program_of(content)
    if program is None:
        return []
    named = _named(program)
    if offered is None and any(ref.tool_name is not None for _, ref in named):
        return [
            {
                "kind": "unavailable_reference",
                "id": None,
                "position": None,
                "message": "Couldn't check the tools this skill names; try again.",
            }
        ]
    found: list[Problem] = []
    for at, ref in named:
        tool = ref.tool_name
        where = f"Step {at['step']}" if at["step"] is not None else "The not-when line"
        if tool is not None and offered is not None and tool not in offered:
            found.append(
                {
                    "kind": "missing_reference",
                    "id": f"{ref.kind}:{ref.id}",
                    "position": at,
                    "message": f"{where} names {ref.id}, which this team no longer offers.",
                }
            )
        if ref.kind == "skill":
            target = await skills.skill(ref.id)
            if target is None or target.team_id != team_id or not target.published or target.deprecated:
                found.append(
                    {
                        "kind": "missing_reference",
                        "id": f"skill:{ref.id}",
                        "position": at,
                        "message": f"{where} names the skill {ref.id}, which is not published in this team.",
                    }
                )
    return found
