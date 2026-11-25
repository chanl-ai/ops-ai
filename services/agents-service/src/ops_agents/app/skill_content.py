"""A skill's steps when it is saved and when a publish is asked for. A save refuses a program that could not run
(a mistyped rule, a jump to nowhere, steps beside parts, a sub-skill that is missing or runs a skill itself) and a
step that changes something with no rule check behind it, marks each check by who judges it, and adds what the steps
name to the skill's own tools and knowledge bases. A publish check lists, with the step it is in, every tool or skill
a step names that the team no longer offers, every step that runs no tool and names exactly one, and, as warnings
that do not block, the other tools a sentence names and its step does not run.

A step runs the tool stored as its `use` and no other: nothing here or in the kernel reads a tool out of a sentence.

It reads the team's skills through `TeamSkills` and is given the tools the directory offers, never a `Runtime`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict

from pydantic import ValidationError

from ops_agent_kernel import steps
from ops_agent_kernel.steps import Ref, SkillProgram
from ops_service_kit import narrow
from ops_service_kit.errors import ValidationFailed
from ops_service_kit.http import Json

from . import skill_text

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
        # Only ever a warning: a tool a step's sentence names and the step does not run.
        "mention",
        # Only ever a warning: a hint the reader put on a line of a skill written as text.
        "hint",
    ]
    id: str | None
    position: Position | None
    message: str


class BlockerWire(TypedDict):
    """A publish problem in the one shape the agent, skill and workflow publish checks return (`schemas.Blocker`)."""

    node: str | None
    field: str | None
    level: Literal["error", "warning"]
    code: str
    message: str


def blocker_of(problem: Problem) -> BlockerWire:
    """A publish problem as a `Blocker`: the field it is in, and no step id, which only a workflow has. An eval problem
    names no field, so it may carry no position."""
    position = problem.get("position")
    field = position["field"] if position else None
    return {"node": None, "field": field, "level": "error", "code": problem["kind"], "message": problem["message"]}


def runs_of(content: Json) -> frozenset[str]:
    """The ids of the skills a stored version's steps run."""
    program = program_of(content)
    if program is None:
        return frozenset()
    return frozenset(s.use.id for s in program.steps if s.use is not None and s.use.kind == "skill")


def program_of(content: Json) -> SkillProgram | None:
    """A stored version's program, as stored; None for a skill without steps. Stored content was checked when it was
    saved."""
    if not content.get("steps"):
        return None
    return SkillProgram.model_validate({k: content[k] for k in KEYS if k in content})


def unruled(program: SkillProgram, access: Mapping[str, str]) -> list[steps.StepProblem]:
    """The steps that run a tool that changes something (`steps.changes`, by the directory's `access` for each tool)
    and carry no rule check. A sentence check is judged by the model, so it cannot be the only thing that says a
    write went through; the rule runs in code on the tool's result, and its "if not" decides what follows."""
    found: list[steps.StepProblem] = []
    for n, step in enumerate(program.steps, start=1):
        name = step.use.tool_name if step.use is not None else None
        # The directory lists a tool by its grant id; the kernel judges it by the name it is called by.
        if step.use is None or name is None or not steps.changes(name, access.get(step.use.grant or "")):
            continue
        if step.check is None or step.check.by != "rule":
            found.append(
                steps.StepProblem(
                    "write_needs_rule",
                    n,
                    f"Step {n} runs {name}, which changes something, so it needs a check written as a rule on its "
                    "result, such as exists(result.id). A check written as a sentence is judged by the model.",
                )
            )
    return found


def refuse_unruled(program: SkillProgram | None, access: Mapping[str, str]) -> None:
    """Refuses a save (400 `write_needs_rule`, with the step) whose step changes something with no rule check."""
    if program is not None and (found := unruled(program, access)):
        raise _refused(found[0])


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
    tools = [name for ref in refs if (name := ref.grant) is not None]
    bases = [ref.id for ref in refs if ref.kind == "knowledge"]
    return list(dict.fromkeys(tools)), list(dict.fromkeys(bases))


def _mentions(program: SkillProgram) -> tuple[list[Problem], list[Problem]]:
    """(problems, warnings) for the tools, agents and workflows a step's sentence names and the step does not run.
    A step that runs nothing and names exactly one blocks the publish: its author most likely meant the step to run
    it, and published as it is the tool would be no step's tool. Any other such mention is a warning."""
    problems: list[Problem] = []
    warnings: list[Problem] = []
    for n, step in enumerate(program.steps, start=1):
        at: Position = {"field": "steps", "step": n, "index": None}
        ran = step.use.token if step.use is not None else None
        named = [r for r in Ref.found_in(step.do) if r.tool_name is not None and r.token != ran]
        if step.use is None and len(named) == 1:
            problems.append(
                {
                    "kind": "bad_step",
                    "id": f"{named[0].kind}:{named[0].id}",
                    "position": at,
                    "message": f"Step {n} names {named[0].id} and runs nothing. Mark it as this step's tool, or "
                    "take it out of the sentence.",
                }
            )
            continue
        for ref in named:
            warnings.append(
                {
                    "kind": "mention",
                    "id": f"{ref.kind}:{ref.id}",
                    "position": at,
                    "message": f"Step {n} mentions {ref.id}, which this step does not run.",
                }
            )
    return problems, warnings


def unrunnable(
    program: SkillProgram, access: Mapping[str, str], *, text: bool = False
) -> tuple[list[Problem], list[Problem]]:
    """(problems, warnings) for steps that must not run as they are stored: a step that changes something with no
    rule check, and a step that runs nothing and names exactly one tool. The one list a draft's publish check, an
    attach and an agent's publish check all read, so a version published before a check existed is held to it too.

    A skill written as text (`text`) is held to neither, here or when it is attached: its step's tool is the one its
    line mentions, and a tool that changes something behind a condition the agent decides is a hint on its line
    (`skill_text.read`). Its publish is stopped only by a mention of something that no longer exists, by steps that
    cannot run, and, in a team with strict publishing, by that hint (`publish_problems`)."""
    if text:
        return [], []
    found, warnings = _mentions(program)
    for p in unruled(program, access):
        spot: Position = {"field": "steps", "step": p.step, "index": None}
        found.append({"kind": "bad_check", "id": None, "position": spot, "message": p.message})
    return found, warnings


def pin_problems(pins: Sequence[Json], access: Mapping[str, str] | None) -> list[Problem]:
    """What in the skills an agent version pins stops the agent's publish: `unrunnable` for each pinned copy, named
    by its skill. `access` is None when the tools directory could not answer, which blocks with one problem."""
    stepped = [(pin, program) for pin in pins if (program := program_of(pin)) is not None and not pin.get("fromText")]
    if access is None and stepped:
        return [
            {
                "kind": "unavailable_reference",
                "id": None,
                "position": {"field": "skills", "step": None, "index": None},
                "message": "Couldn't check the tools this agent's skills name; try again.",
            }
        ]
    found: list[Problem] = []
    for pin, program in stepped:
        for p in unrunnable(program, access or {})[0]:
            step = p["position"]["step"] if p["position"] is not None else None
            found.append(
                {
                    "kind": p["kind"],
                    "id": f"skill:{pin.get('skillId')}",
                    "position": {"field": "skills", "step": step, "index": None},
                    "message": f"{pin.get('name')} v{pin.get('version')}: {p['message']} Fix the skill, publish it and "
                    "attach the new version.",
                }
            )
    return found


async def missing(
    refs: Sequence[Ref],
    offered: Mapping[str, str] | None,
    bases: Mapping[str, str] | None,
    *,
    team_id: str,
    skills: TeamSkills,
) -> dict[str, str]:
    """The mentions (`@kind:id` to a name) of things that no longer exist: a tool, agent or workflow the directory
    does not offer (`offered`, None when it could not answer), a knowledge base not among `bases` (id to name, None
    when unknown), or a skill that is not a published skill of the team. The one answer to "is this mention still
    good" for a skill's text, read by the publish check and by the editor's read call."""
    gone: dict[str, str] = {}
    for ref in refs:
        if ref.kind == "knowledge":
            if bases is not None and ref.id not in bases:
                gone[ref.token] = ref.id
        elif ref.kind == "skill":
            target = await skills.skill(ref.id)
            if target is None or target.team_id != team_id or not target.published or target.deprecated:
                gone[ref.token] = target.name if target is not None else ref.id
        elif (grant := ref.grant) is not None and offered is not None and grant not in offered:
            gone[ref.token] = ref.id
    return gone


async def publish_problems(
    content: Json,
    offered: Mapping[str, str] | None,
    *,
    team_id: str,
    skills: TeamSkills,
    bases: Mapping[str, str] | None = None,
    fields: Mapping[str, skill_text.Fields] | None = None,
    labels: Mapping[str, str] | None = None,
    strict: Callable[[], Awaitable[bool | None]] | None = None,
) -> tuple[list[Problem], list[Problem]]:
    """What in the skill's steps blocks a publish, and the warnings that do not. `offered` is the access of each tool
    the directory offers now, by id; None when it could not answer, which blocks the publish with one problem, since
    nothing can be checked.

    A skill written as text is read as the editor reads it (`fields`, `labels`), and is blocked only by a mention of
    something that no longer exists or by steps that cannot run, each pointed at by its line (`position.index`, from
    1, in the field `source`); every hint is a warning. `strict` answers whether the owning team publishes a tool
    that changes something only behind a checked condition (None when the setting could not be read, which counts as
    on); it is asked only when the text has such a line, and on it each one blocks."""
    source = content.get("source")
    if isinstance(source, str):
        refs = Ref.found_in(source)
        if offered is None and any(r.grant is not None for r in refs):
            return [
                {
                    "kind": "unavailable_reference",
                    "id": None,
                    "position": None,
                    "message": "Couldn't check the tools this skill mentions; try again.",
                }
            ], []
        gone = await missing(refs, offered, bases, team_id=team_id, skills=skills)
        declared = {str(k): str(v) for k, v in narrow.json_object(content.get("exit")).items()}
        # Always on or in parts, the text never runs as steps, so its length blocks nothing.
        plain = "plain" if content.get("loading") == "always" or content.get("parts") else None
        reading = skill_text.read(
            source, fields=fields, labels=labels, missing=gone, exits=declared, plain=plain, access=offered
        )
        found: list[Problem] = [
            {
                "kind": "missing_reference",
                "id": e["id"],
                "position": {"field": "source", "step": None, "index": e["line"]},
                "message": e["message"],
            }
            for e in reading.errors
        ]
        unrun: list[Problem] = [
            {
                "kind": "bad_step",
                "id": None,
                "position": {"field": "source", "step": None, "index": n["line"]},
                "message": n["message"],
            }
            for n in reading.unrun
        ]
        # Read only when a line would be refused by it; an unread setting counts as on.
        held = bool(reading.unguarded) and strict is not None and (await strict()) is not False
        refused: list[Problem] = [
            {
                "kind": "bad_check",
                "id": None,
                "position": {"field": "source", "step": None, "index": n["line"]},
                "message": f"This team publishes a change only behind a condition checked on a tool's result. "
                f"{n['message']}",
            }
            for n in (reading.unguarded if held else [])
        ]
        hints: list[Problem] = [
            {
                "kind": "hint",
                "id": None,
                "position": {"field": "source", "step": None, "index": n["line"]},
                "message": n["message"],
            }
            for n in reading.hints
            if not (held and n in reading.unguarded)
        ]
        return [*found, *unrun, *refused], hints
    program = program_of(content)
    if program is None:
        return [], []
    named = _named(program)
    if offered is None and any(ref.tool_name is not None for _, ref in named):
        return [
            {
                "kind": "unavailable_reference",
                "id": None,
                "position": None,
                "message": "Couldn't check the tools this skill names; try again.",
            }
        ], []
    found, warnings = unrunnable(program, offered or {})
    for at, ref in named:
        tool = ref.grant
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
    return found, warnings
