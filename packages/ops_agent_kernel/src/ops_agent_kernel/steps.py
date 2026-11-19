"""Skills with steps: the program a skill version stores, the problems that stop one from running, and how the
record of a running skill moves from step to step.

The models live in `ops_contracts.skill_run`, because the record carries the program of the version that started and
the console and SDKs read it; they are re-exported here, where the kernel's rules for them are.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import JsonValue

from ops_contracts.skill_run import (
    BUILT_IN_EXITS,
    HISTORY_MAX,
    REF_TOKEN,
    RESULT_MAX,
    EndedSkill,
    HeldTools,
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
from ops_pii import holds_placeholder
from ops_service_kit.http import Json
from ops_service_kit.narrow import json_object

from . import expr
from .prompt_writer import Now
from .types import Skill

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
    "denied",
    "halted",
    "held",
    "judged",
    "leave",
    "missing_inputs",
    "now",
    "on_result",
    "problems",
    "said",
    "shown",
    "start",
    "step_done",
    "target",
    "withheld",
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


# --- the record of a running skill ---
#
# Every function below takes the record and returns a new one; the record handed in is never changed, so a turn that
# stops half-way keeps the one it had.

# How many times one step may send the skill to another step before the skill ends as failed: a pair of steps that
# send to each other would otherwise never end.
GOTO_MAX = 3


@dataclass(frozen=True)
class Moved:
    """A record after one event, and what the model is told about it. `ok` is False when the event was refused and
    nothing moved."""

    run: SkillRunState
    said: str
    ok: bool = True


def _frame(r: RunningSkill) -> RunningSkill | SubRun:
    """The skill whose step is current: the sub-skill while one runs, else the skill itself."""
    return r.sub or r


def _step(f: RunningSkill | SubRun) -> SkillStep:
    return f.program.steps[f.step - 1]


def _required(program: SkillProgram) -> tuple[str, ...]:
    return tuple(x.name for x in program.returns if x.required)


def _owes(f: RunningSkill | SubRun) -> bool:
    """Every step has passed and the skill still has results to hand back: it waits for exit."""
    last = f.results.get(str(len(f.program.steps)))
    return f.step == len(f.program.steps) and last is not None and last.passed is True


def _kept(value: Any, passed: bool | None) -> StepResult:
    try:
        size = len(json.dumps(value))
    except (TypeError, ValueError):
        return StepResult(passed=passed, truncated=True)
    if size > RESULT_MAX:
        return StepResult(passed=passed, truncated=True)
    return StepResult(passed=passed, value=value)


def _is_rule(check: StepCheck) -> bool:
    if check.by is not None:
        return check.by == "rule"
    try:
        return expr.kind_of(check.text) == "rule"
    except expr.CheckError:
        # A text that reads as a rule and is not one is never the model's to confirm: it fails as a rule.
        return True


def _hidden(check: StepCheck, f: RunningSkill | SubRun) -> list[str]:
    """The inputs `check` reads that the record holds masked: a record carried from an earlier reply keeps a
    placeholder where personal data was, and a rule never compares one."""
    if not f.masked_inputs:
        return []
    try:
        read = expr.inputs_read(check.text)
    except expr.CheckError:
        return []
    return sorted(f.masked_inputs) if expr.EVERY_INPUT in read else sorted(read & set(f.masked_inputs))


def _holds(check: StepCheck, value: Any, f: RunningSkill | SubRun, told: list[str]) -> bool:
    """Whether a rule check holds for a step of `f`. A rule that reads a masked input does not hold, and `told`
    gets the sentence that says why."""
    if hidden := _hidden(check, f):
        named = ", ".join(hidden)
        told.append(
            f"This step's check reads the input {named}, which is masked in what this conversation keeps, so the "
            "check could not run and the step did not pass. Do not compare it yourself."
        )
        return False
    try:
        return expr.evaluate(check.text, {"result": value, "inputs": f.inputs})
    except expr.CheckError:
        return False


# Endings after which a skill's step tools are free again: it finished, or another skill took its place.
RELEASES = ("done", "switched")


def _tools(r: RunningSkill, skills: Sequence[Skill]) -> set[str]:
    """Every tool a step of the running skill calls, and every tool a step of a skill it runs calls, whether or not
    that skill was reached."""
    out = set(r.program.targets())
    if r.sub is not None:
        out |= r.sub.program.targets()
    runs = {s.use.id for s in r.program.steps if s.use is not None and s.use.kind == "skill"}
    for s in skills:
        if s.skill_id in runs and s.program is not None:
            out |= s.program.targets()
    return out


def _end(
    run: SkillRunState,
    name: str,
    skills: Sequence[Skill],
    returns: dict[str, JsonValue] | None = None,
    *,
    holds: bool = True,
) -> None:
    """Ends the running skill. One that ends as failed holds its step tools from then on, unless `holds` is off:
    a skill stopped because another failed skill holds its tool has failed no check of its own."""
    r = run.running
    assert r is not None
    tools = _tools(r, skills) if holds else set[str]()
    if name == "failed" and tools:
        kept = run.held_by_failed.get(r.skill_id)
        both = sorted(tools | set(kept.tools if kept is not None else []))
        run.held_by_failed[r.skill_id] = HeldTools(slug=r.slug, name=r.name, tools=both)
    run.history.append(
        EndedSkill(
            skill_id=r.skill_id,
            version=r.version,
            name=r.name,
            ended=name,
            at_step=r.step,
            tools=[] if name in RELEASES else sorted(tools),
            returns=returns or {},
        )
    )
    del run.history[:-HISTORY_MAX]
    run.running = None


def _text(value: Any) -> str | None:
    """A step result's field as an input, which is text; None for a value that is not one plain value."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int | float):
        return json.dumps(value)
    return None


def _handed(r: RunningSkill, n: int, sub: Skill) -> tuple[dict[str, str], list[str]]:
    """The inputs the skill step `n` starts gets, by the names it declares, and which of them are masked. An input
    of the running skill comes first; one it does not have is read by name from the result of the step before."""
    before = r.results.get(str(n - 1))
    fields = json_object(before.value) if before is not None else {}
    inputs: dict[str, str] = {}
    masked: list[str] = []
    for name in (i.name for i in sub.inputs):
        own = r.inputs.get(name, "")
        if own.strip():
            inputs[name] = own
            if name in r.masked_inputs:
                masked.append(name)
        elif (found := _text(fields.get(name))) is not None and found.strip():
            inputs[name] = found
            # A result a carried record kept is masked: its placeholder is not a value to compare.
            if holds_placeholder(found):
                masked.append(name)
    return inputs, masked


def _enter(run: SkillRunState, n: int, skills: Sequence[Skill], told: list[str]) -> None:
    """Puts the running skill on step `n`. A step that runs a skill starts it here, one level deep: a skill the agent
    does not hold, one whose own steps run a skill, or one left without an input it requires is a failed attempt of
    the step."""
    r = run.running
    assert r is not None
    step = r.program.steps[n - 1]
    r.step, r.step_text, r.sub = n, step.do, None
    r.results.pop(str(n), None)
    if step.use is None or step.use.kind != "skill":
        return
    sub = next((s for s in skills if s.skill_id == step.use.id and s.program is not None), None)
    program = sub.program if sub is not None else None
    if sub is None or program is None or not program.steps or sub.skill_id == r.skill_id:
        _failed(run, skills, told)
        return
    if any(x.use is not None and x.use.kind == "skill" for x in program.steps):
        _failed(run, skills, told)
        return
    inputs, masked = _handed(r, n, sub)
    if missing := missing_inputs(sub, inputs):
        why = (
            f"{sub.name} did not start: it needs {', '.join(missing)}, and neither the inputs of {r.name} nor the "
            f"result of the step before step {n} has {'it' if len(missing) == 1 else 'them'}."
        )
        if why not in told:
            told.append(why)
        _failed(run, skills, told)
        return
    r.sub = SubRun(
        skill_id=sub.skill_id,
        version=sub.version,
        slug=sub.slug,
        name=sub.name,
        step=1,
        steps_total=len(program.steps),
        step_text=program.steps[0].do,
        return_to=n,
        inputs=inputs,
        masked_inputs=masked,
        program=program,
        rules=sub.instructions,
    )


def _failed(run: SkillRunState, skills: Sequence[Skill], told: list[str]) -> None:
    """The current step did not pass: its "if not" decides. With none, it is tried once more."""
    r = run.running
    assert r is not None
    f = _frame(r)
    key = str(f.step)
    f.attempts[key] = f.attempts.get(key, 0) + 1
    rule = _step(f).if_not or IfNot()
    again = rule.action == "retry" and f.attempts[key] <= rule.retries
    goto = rule.step if rule.action == "goto" and f.attempts[key] <= GOTO_MAX else None
    if goto is not None and goto > len(f.program.steps):
        goto = None
    ends = rule.exit if rule.action == "exit" and rule.exit else "failed"
    if isinstance(f, SubRun):
        if again:
            return
        if goto is not None:
            f.step, f.step_text = goto, f.program.steps[goto - 1].do
            f.results.pop(str(goto), None)
            return
        _sub_ended(run, skills, ends, {}, told)
        return
    if again:
        if (use := _step(r).use) is not None and use.kind == "skill":
            _enter(run, r.step, skills, told)
        return
    if goto is not None:
        _enter(run, goto, skills, told)
        return
    _end(run, ends, skills)


def _own(run: SkillRunState) -> set[str]:
    """The tools the running skill holds itself since it failed. Started again, it is proving its own check once
    more, so no other skill's hold on one of these stops it: two failed skills that name the same tool would
    otherwise lock it for the whole conversation."""
    r = run.running
    kept = run.held_by_failed.get(r.skill_id) if r is not None else None
    return set(kept.tools) if kept is not None else set()


def _held_for(run: SkillRunState) -> HeldTools | None:
    """The failed skill that holds the current step's tool, when it is not the skill running."""
    r = run.running
    tool = target(run)
    if r is None or tool is None or tool in _own(run):
        return None
    return next((h for sid, h in run.held_by_failed.items() if sid != r.skill_id and tool in h.tools), None)


def _stop_if_held(run: SkillRunState, skills: Sequence[Skill], told: list[str]) -> None:
    """Ends the running skill as failed when its current step calls a tool another failed skill holds: the tool is
    not offered, so the step could never be done. It holds nothing for this: no check of its own failed."""
    if (holder := _held_for(run)) is None:
        return
    told.append(f"{target(run)} is held because {holder.slug} failed its check; start {holder.slug} again.")
    _end(run, "failed", skills, holds=False)


def _released(run: SkillRunState, f: RunningSkill | SubRun) -> None:
    """The running skill passed the current step of `f`: what it held of that step's tool since it failed is free."""
    r = run.running
    assert r is not None
    use = _step(f).use
    kept = run.held_by_failed.get(r.skill_id)
    if kept is None or use is None or use.tool_name not in kept.tools:
        return
    left = [t for t in kept.tools if t != use.tool_name]
    if left:
        run.held_by_failed[r.skill_id] = kept.model_copy(update={"tools": left})
    else:
        del run.held_by_failed[r.skill_id]


def _passed(run: SkillRunState, skills: Sequence[Skill], value: Any, told: list[str]) -> None:
    r = run.running
    assert r is not None
    f = _frame(r)
    _released(run, f)
    f.results[str(f.step)] = _kept(value, True)
    if f.step < len(f.program.steps):
        if isinstance(f, SubRun):
            f.step += 1
            f.step_text = _step(f).do
            f.results.pop(str(f.step), None)
        else:
            _enter(run, r.step + 1, skills, told)
        return
    if _required(f.program):
        return
    if isinstance(f, SubRun):
        _sub_ended(run, skills, "done", {}, told)
    else:
        _end(run, "done", skills)


def _sub_ended(
    run: SkillRunState, skills: Sequence[Skill], name: str, returns: dict[str, JsonValue], told: list[str]
) -> None:
    """A sub-skill ended: the step that started it gets its exit and results as that step's result, and the step's
    own check runs on them. A sub-skill that failed is a failed attempt of the step."""
    r = run.running
    assert r is not None
    r.sub = None
    value: dict[str, JsonValue] = {"exit": name, **returns}
    check = _step(r).check
    if name == "failed" or (check is not None and _is_rule(check) and not _holds(check, value, r, told)):
        r.results[str(r.step)] = _kept(value, False)
        _failed(run, skills, told)
        return
    _passed(run, skills, value, told)


def said(before: SkillRunState, after: SkillRunState) -> str:
    """What the model is told after an event, from where the record was and where it is."""
    was = before.running
    now_ = after.running
    if now_ is None:
        ended = after.history[-1]
        if ended.ended == "done":
            return f"{ended.name} is done."
        return f"{ended.name} ended as {ended.ended} on step {ended.at_step}. Tell the person what was not done."
    f = _frame(now_)
    step = _step(f)
    at = (f.skill_id, f.step)
    if was is not None and (_frame(was).skill_id, _frame(was).step) == at:
        if _owes(f):
            return (
                f"Every step of {f.name} is done. Call exit with the name done and: {', '.join(_required(f.program))}."
            )
        res = f.results.get(str(f.step))
        if res is not None and res.passed is None and step.check is not None:
            return f"Now confirm: {step.check.text} Call step_done once it holds."
        rule = step.if_not or IfNot()
        left = max(rule.retries - f.attempts.get(str(f.step), 0), 0) if rule.action == "retry" else 0
        return (
            f"Step {f.step} of {f.name} did not pass its check. Ask the person for what is missing and try again "
            f"({left} more {'try' if left == 1 else 'tries'} before the skill ends as failed)."
        )
    return f"Now on {f.name}, step {f.step} of {len(f.program.steps)}: {step.do}"


def start(
    run: SkillRunState,
    skill: Skill,
    skills: Sequence[Skill],
    *,
    by: Literal["menu", "model"],
    inputs: dict[str, str] | None = None,
    told: list[str] | None = None,
) -> SkillRunState:
    """The record with `skill` running from step 1. A skill that was running ends as switched: nothing stacks.
    `told` gets what the model must hear when the first step could not start the skill it runs."""
    program = skill.program
    assert program is not None and program.steps
    run = run.model_copy(deep=True)
    if run.running is not None:
        _end(run, "switched", skills)
    run.running = RunningSkill(
        skill_id=skill.skill_id,
        version=skill.version,
        slug=skill.slug,
        name=skill.name,
        step=1,
        steps_total=len(program.steps),
        step_text=program.steps[0].do,
        started_by=by,
        inputs=inputs or {},
        program=program,
        rules=skill.instructions,
    )
    told = [] if told is None else told
    _enter(run, 1, skills, told)
    _stop_if_held(run, skills, told)
    return run


def target(run: SkillRunState) -> str | None:
    """The tool the current step calls, by the name it is granted under; None when the step calls none."""
    r = run.running
    if r is None or _owes(_frame(r)):
        return None
    use = _step(_frame(r)).use
    return use.tool_name if use is not None else None


def withheld(run: SkillRunState, skills: Sequence[Skill]) -> set[str]:
    """Tools not offered now: every tool a step of the running skill (or of a skill its steps run) calls, except the
    current step's, so a later step's write cannot be called before its own step; and the tools a failed skill
    holds, to every skill but itself. A held tool stays out even as the current step's tool of another skill, so
    its write cannot run through a skill that skips the check that failed."""
    r = run.running
    out: set[str] = set() if r is None else _tools(r, skills) - {target(run)}
    for skill_id, kept in run.held_by_failed.items():
        if r is None or r.skill_id != skill_id:
            out |= set(kept.tools) - _own(run)
    return out


def on_result(run: SkillRunState, skills: Sequence[Skill], output: Any, ok: bool) -> Moved:
    """The current step's tool answered. A rule check runs here, once, on the result as it arrived; a step with no
    check passes when its tool ran; a sentence check waits for the model's step_done."""
    before = run
    run = run.model_copy(deep=True)
    r = run.running
    assert r is not None
    f = _frame(r)
    step = _step(f)
    key = str(f.step)
    told: list[str] = []
    if not ok:
        f.results[key] = _kept(output, False)
        _failed(run, skills, told)
    elif step.check is None:
        _passed(run, skills, output, told)
    elif _is_rule(step.check):
        if _holds(step.check, output, f, told):
            _passed(run, skills, output, told)
        else:
            f.results[key] = _kept(output, False)
            _failed(run, skills, told)
    else:
        f.results[key] = _kept(output, None)
    _stop_if_held(run, skills, told)
    return Moved(run, " ".join([*told, said(before, run)]))


def step_done(run: SkillRunState, skills: Sequence[Skill]) -> Moved:
    """The model says the current step is done. Refused while the step's tool has not run, and for a rule check on a
    tool result, which is never the model's to confirm."""
    r = run.running
    if r is None:
        return Moved(run, "No skill is running.", ok=False)
    f = _frame(r)
    step = _step(f)
    res = f.results.get(str(f.step))
    if _owes(f):
        owed = ", ".join(_required(f.program))
        return Moved(run, f"Every step is done. Call exit with the name done and: {owed}.", ok=False)
    use = step.use.tool_name if step.use is not None else None
    if use is not None and res is None:
        return Moved(run, f"Call {use} first: step {f.step} is done when it has run.", ok=False)
    rule = step.check is not None and _is_rule(step.check)
    if rule and use is not None:
        return Moved(run, "The check for this step runs on the tool result; it is not yours to confirm.", ok=False)
    before = run
    run = run.model_copy(deep=True)
    assert run.running is not None
    told: list[str] = []
    if rule and step.check is not None and not _holds(step.check, None, _frame(run.running), told):
        _frame(run.running).results[str(f.step)] = _kept(None, False)
        _failed(run, skills, told)
    else:
        _passed(run, skills, res.value if res is not None else None, told)
    _stop_if_held(run, skills, told)
    return Moved(run, " ".join([*told, said(before, run)]))


def _results(program: SkillProgram, given: Json, *, failed: bool) -> dict[str, JsonValue] | str:
    """The results an exit hands back, checked against the skill's list; a sentence when they do not fit."""
    fields = {x.name: x for x in program.returns}
    if unknown := sorted(set(given) - set(fields)):
        return f"{', '.join(unknown)} {'is' if len(unknown) == 1 else 'are'} not a result of this skill."
    clean: dict[str, JsonValue] = {}
    for name, spec in fields.items():
        value = given.get(name)
        if value is None:
            if spec.required and not failed:
                return f"The result {name} is required."
            continue
        fits = {
            "text": isinstance(value, str),
            "number": isinstance(value, int | float) and not isinstance(value, bool),
            "yes_no": isinstance(value, bool),
        }[spec.type]
        if not fits:
            words = {"text": "text", "number": "a number", "yes_no": "true or false"}[spec.type]
            return f"The result {name} must be {words}."
        clean[name] = cast(JsonValue, value)
    return clean


def leave(run: SkillRunState, skills: Sequence[Skill], name: str, returns: Json) -> Moved:
    """The model ends the current skill with an exit. `done` is accepted only on the last step once it has passed;
    an exit the skill lists, and `failed`, are accepted on any step."""
    r = run.running
    if r is None:
        return Moved(run, "No skill is running.", ok=False)
    f = _frame(r)
    program = f.program
    if name not in program.exits():
        return Moved(
            run, f"{name} is not an exit of {f.name}. Use one of: {', '.join(sorted(program.exits()))}.", ok=False
        )
    step = _step(f)
    res = f.results.get(str(f.step))
    if name == "done":
        ran = step.use is None or res is not None
        rule = step.check is not None and _is_rule(step.check)
        if f.step != len(program.steps) or not ran or (rule and not (res is not None and res.passed is True)):
            return Moved(
                run,
                f"{f.name} is on step {f.step} of {len(program.steps)}: {step.do} It ends as done only after its "
                "last step has passed. Do this step, or end with another exit if it cannot be done.",
                ok=False,
            )
    clean = _results(program, returns, failed=name == "failed")
    if isinstance(clean, str):
        return Moved(run, clean, ok=False)
    before = run
    run = run.model_copy(deep=True)
    assert run.running is not None
    told: list[str] = []
    if run.running.sub is not None:
        _sub_ended(run, skills, name, clean, told)
    else:
        _end(run, name, skills, clean)
    _stop_if_held(run, skills, told)
    return Moved(run, " ".join([*told, said(before, run)]))


def denied(run: SkillRunState, skills: Sequence[Skill]) -> SkillRunState:
    """A person rejected the current step's call: the skill ends as failed at once."""
    if run.running is None:
        return run
    run = run.model_copy(deep=True)
    _end(run, "failed", skills)
    return run


def missing_inputs(skill: Skill, inputs: Mapping[str, str]) -> list[str]:
    """The inputs `skill` requires that `inputs` leaves out or blank, in the order the skill declares them."""
    return [i.name for i in skill.inputs if i.required and not str(inputs.get(i.name) or "").strip()]


def held(before: SkillRunState, after: SkillRunState) -> tuple[str, list[str]] | None:
    """The skill an event stopped, and the tools its steps call, when it ended any way but done or switched: those
    tools are not offered for the rest of the reply unless that skill starts again."""
    was, now_ = before.running, after.running
    left = was is not None and (now_ is None or now_.skill_id != was.skill_id)
    if not after.history or not (left or after.history != before.history):
        return None
    last = after.history[-1]
    return None if last.ended in RELEASES else (last.skill_id, last.tools)


def halted(run: SkillRunState, skills: Sequence[Skill], reply_holds: Mapping[str, Sequence[str]]) -> Moved | None:
    """The record with the running skill ended as failed, and what the model is told, when its current step calls a
    tool a skill stopped earlier in this reply still holds (`reply_holds`, by skill id); None when it does not. The
    same rule as for a failed skill's hold: the skill does not stay on a step whose tool is not offered."""
    r = run.running
    tool = target(run)
    if r is None or tool is None:
        return None
    holder = next((sid for sid, tools in reply_holds.items() if sid != r.skill_id and tool in tools), None)
    if holder is None:
        return None
    before = run
    run = run.model_copy(deep=True)
    slug = next((s.slug for s in skills if s.skill_id == holder), holder)
    how = next((h.ended for h in reversed(run.history) if h.skill_id == holder), "stopped")
    why = f"{tool} is held for the rest of this reply because {slug} ended as {how}; start {slug} again."
    _end(run, "failed", skills, holds=False)
    return Moved(run, f"{why} {said(before, run)}")


def shown(text: str, names: Mapping[str, str]) -> str:
    """`text` with each `@kind:id` reference replaced by the name the model knows it under; an id with no name stays."""
    return REF_TOKEN.sub(lambda m: names.get(m.group(0), m.group(2)), text)


def now(run: SkillRunState, names: Mapping[str, str]) -> Now | None:
    """The current step in the words the prompt gives the model; None when no skill is running."""
    r = run.running
    if r is None:
        return None
    f = _frame(r)
    step = _step(f)
    use = None
    if step.use is not None:
        use = names.get(step.use.token) or step.use.tool_name or step.use.id
    check = step.check
    if check is not None and check.by is None:
        check = check.model_copy(update={"by": "rule" if _is_rule(check) else "model"})
    return Now(
        skill=f.name,
        step=f.step,
        of=len(f.program.steps),
        do=shown(step.do, names),
        use=use,
        check=check,
        if_not=step.if_not,
        inside=r.name if r.sub is not None else None,
        rules=f.rules,
        owes=_required(f.program) if _owes(f) else None,
    )
