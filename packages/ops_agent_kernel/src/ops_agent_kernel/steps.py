"""Skills with steps: the program a skill version stores, the problems that stop one from running, and how the
record of a running skill moves from step to step.

The models live in `ops_contracts.skill_run`, because the record carries the program of the version that started and
the console and SDKs read it; they are re-exported here, where the kernel's rules for them are.
"""

from __future__ import annotations

import json
import math
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
    EndedWhy,
    Hold,
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
    hands_to_agent,
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
    "barred",
    "changes",
    "denied",
    "ending",
    "final",
    "halted",
    "held",
    "judged",
    "leave",
    "missing_inputs",
    "now",
    "on_result",
    "owned",
    "problems",
    "said",
    "shown",
    "start",
    "step_done",
    "target",
    "trim",
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
                rule = expr.kind_of(step.check.text) == "rule"
                if rule and step.use is None and expr.reads_result(step.check.text):
                    found.append(
                        StepProblem(
                            "check_needs_tool",
                            n,
                            f"Step {n}'s check reads a result, and the step runs no tool to get it from. Pick the "
                            "tool it runs with @, or mark the one its sentence names as this step's tool.",
                        )
                    )
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
# The reasons for an ending the kernel made. Such an ending is final for the reply it happened in: the model cannot
# start the skill again until the person's next message. An exit the model called itself is not among them.
FINAL: tuple[EndedWhy, ...] = ("check", "denied", "error", "held")


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


def trim(run: SkillRunState) -> None:
    """Keeps the newest `HISTORY_MAX` endings, and every ending made in this reply however many came after it: that
    one is what keeps its skill from starting again (`final`), so it is forgotten only once the reply is over."""
    cut = len(run.history) - HISTORY_MAX
    run.history = [h for i, h in enumerate(run.history) if i >= cut or h.in_reply]


def _end(
    run: SkillRunState,
    name: str,
    skills: Sequence[Skill],
    returns: dict[str, JsonValue] | None = None,
    *,
    holds: bool = True,
    why: EndedWhy | None = None,
    check: str | None = None,
) -> None:
    """Ends the running skill, and records how: the exit, the step, and for any ending but done or switched the
    reason (`why`, with the text of the check that did not pass) and what the author wrote the exit means. Its step
    tools are kept from the rest of the reply unless it ended as done or switched, or `holds` is off: a skill
    stopped because another skill holds its tool keeps nothing. What lasts beyond the reply is taken where a check
    fails or a call is denied (`_hold`), not here."""
    r = run.running
    assert r is not None
    tools = _tools(r, skills) if holds else set[str]()
    stopped = name not in RELEASES
    run.history.append(
        EndedSkill(
            skill_id=r.skill_id,
            version=r.version,
            name=r.name,
            ended=name,
            at_step=r.step,
            tools=sorted(tools) if stopped else [],
            returns=returns or {},
            in_reply=True,
            why=why if stopped else None,
            check=check if stopped and why == "check" else None,
            meaning=r.program.exit.get(name),
        )
    )
    trim(run)
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
        _failed(run, skills, told, "error")
        return
    if any(x.use is not None and x.use.kind == "skill" for x in program.steps):
        _failed(run, skills, told, "error")
        return
    inputs, masked = _handed(r, n, sub)
    if missing := missing_inputs(sub, inputs):
        why = (
            f"{sub.name} did not start: it needs {', '.join(missing)}, and neither the inputs of {r.name} nor the "
            f"result of the step before step {n} has {'it' if len(missing) == 1 else 'them'}."
        )
        if why not in told:
            told.append(why)
        _failed(run, skills, told, "error")
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


def _failed(
    run: SkillRunState, skills: Sequence[Skill], told: list[str], why: EndedWhy, check: str | None = None
) -> None:
    """The current step did not pass: its "if not" decides. With none, it is tried once more. `why`, and the text
    of the `check` that did not pass, go on the record when this ends the skill."""
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
        _sub_ended(run, skills, ends, {}, told, why=why, check=check)
        return
    if again:
        if (use := _step(r).use) is not None and use.kind == "skill":
            _enter(run, r.step, skills, told)
        return
    if goto is not None:
        _enter(run, goto, skills, told)
        return
    _end(run, ends, skills, why=why, check=check)


# --- holds: what a failed check or a denied call keeps from every other skill ---
#
# 1. A hold is taken the moment a step's check fails or a person denies its call, whatever retries are left and
#    however the skill is left afterwards (an exit, a switch, the end of the reply).
# 2. It covers the tools of the steps after that step, those of skills they run included; a denied call's own tool
#    as well; never the tool of the step whose check failed.
# 3. It keeps those tools from every other skill and from a call with no skill running. The holder is never kept
#    from them. A skill ended because its step's tool is held takes no hold.
# 4. It ends when the holder passes the same step, or when the agent no longer has that version of the holder
#    (dropped where a turn starts, in the kernel).
# 5. A step takes no hold while its skill has one standing from that step or an earlier one. Accepted limit: in a
#    skill whose "if not" jumps forward to a step with a check of its own, that later check can fail under the
#    earlier hold, and once the earlier step passes nothing holds the later step's write. Taking the later hold as
#    well would let two skills lock each other for good.
# 6. A tool that answers with an error, a skill a step could not start, and an exit the model calls take none.
# 7. A step that runs a skill passes only when that skill ends as done, unless the step has a rule of its own
#    (`_sub_ended`). An exit therefore never carries the step past a check that failed inside the skill.
#
# A thread cannot lock for good: a check can only fail when its tool was free, and a hold never covers that tool,
# so the newest holder can always run its check again and release.


def _key(r: RunningSkill) -> str:
    """The current step as a hold names it."""
    return f"{r.step}.{r.sub.step}" if r.sub is not None else str(r.step)


def _order(key: str, program: SkillProgram) -> tuple[int, float]:
    """Where a hold's step comes in its skill. A step that runs a skill checks that skill's result after its
    steps, so its own key sorts after theirs."""
    n, _, m = key.partition(".")
    if m:
        return int(n), float(m)
    use = program.steps[int(n) - 1].use if int(n) <= len(program.steps) else None
    return int(n), math.inf if use is not None and use.kind == "skill" else 0.0


def _later(r: RunningSkill, skills: Sequence[Skill]) -> set[str]:
    """The tools of the steps after the current one: the rest of the skill a step is running, then the steps after
    that step, with every tool of the skills they run."""
    out: set[str] = set()
    if r.sub is not None:
        out |= {s.use.tool_name for s in r.sub.program.steps[r.sub.step :] if s.use is not None and s.use.tool_name}
    for s in r.program.steps[r.step :]:
        if s.use is None:
            continue
        if s.use.kind == "skill":
            ran = next((k.program for k in skills if k.skill_id == s.use.id and k.program is not None), None)
            out |= ran.targets() if ran is not None else set()
        elif s.use.tool_name:
            out.add(s.use.tool_name)
    return out


def _hold(run: SkillRunState, skills: Sequence[Skill], *, denied: bool = False) -> None:
    """Takes the hold for the current step, whose check just failed or whose call a person denied."""
    r = run.running
    assert r is not None
    key = _key(r)
    at = _order(key, r.program)
    if any(h.skill_id == r.skill_id and _order(h.step, r.program) <= at for h in run.holds):
        return
    use = _step(_frame(r)).use
    own = use.tool_name if use is not None else None
    tools = _later(r, skills) - {own}
    if denied and own:
        tools.add(own)
    if tools:
        run.holds.append(
            Hold(
                skill_id=r.skill_id,
                version=r.version,
                slug=r.slug,
                name=r.name,
                step=key,
                denied=denied,
                tools=sorted(tools),
            )
        )


def _held_for(run: SkillRunState) -> Hold | None:
    """The hold of another skill on the current step's tool."""
    r = run.running
    tool = target(run)
    if r is None or tool is None:
        return None
    return next((h for h in run.holds if h.skill_id != r.skill_id and tool in h.tools), None)


def _stop_if_held(run: SkillRunState, skills: Sequence[Skill], told: list[str]) -> None:
    """Ends the running skill as failed when its current step calls a tool another skill holds: the tool is not
    offered, so the step could never be done. It takes no hold for this: no check of its own failed."""
    if (hold := _held_for(run)) is None:
        return
    why = f"a person denied a call of {hold.slug}" if hold.denied else f"{hold.slug} failed its check"
    told.append(f"{target(run)} is held because {why}; {_again(run, hold.skill_id, hold.slug)}")
    _end(run, "failed", skills, holds=False, why="held")


def _passed(run: SkillRunState, skills: Sequence[Skill], value: Any, told: list[str]) -> None:
    r = run.running
    assert r is not None
    f = _frame(r)
    key = _key(r)
    run.holds = [h for h in run.holds if not (h.skill_id == r.skill_id and h.step == key)]
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
    run: SkillRunState,
    skills: Sequence[Skill],
    name: str,
    returns: dict[str, JsonValue],
    told: list[str],
    *,
    why: EndedWhy | None = None,
    check: str | None = None,
) -> None:
    """A sub-skill ended: the step that started it gets its exit and results as that step's result. The step passes
    only when the sub-skill ended as done, unless the step has a rule of its own, which then decides: an author who
    wants another ending to go on writes `result.exit in ["done", "skip"]`. So no exit carries a step past a
    check that did not pass inside the sub-skill, however often it is called. A sub-skill that ended as failed is
    always a failed attempt of the step. Neither takes a hold here: a check that failed inside took one where it
    failed. A rule of the step's own that does not hold on a done ending is a failed check like any other, and
    takes one; on any other ending the step fails and takes none.

    The step's result holds what the sub-skill handed back only when it ended as done. With any other exit the model
    names the results itself at any step, so a rule such as `result.ok` would pass on its word; they are left out.
    And after any exit but done the rule has to depend on the exit: it must hold for this exit and not hold for
    `failed`, the one ending no skill lists and no step passes on. A rule that reads something else (an input, a
    result that is not there) says nothing about this ending, so it does not carry the step on.

    `why` and `check` say what ended the sub-skill when it did not finish (a check inside it, the model's exit), and
    go on the record if the step's failure ends the skill."""
    r = run.running
    assert r is not None
    r.sub = None
    value: dict[str, JsonValue] = {"exit": name, **(returns if name == "done" else {})}
    own = _step(r).check
    ruled = own is not None and _is_rule(own)
    if name == "failed" or (not ruled and name != "done"):
        r.results[str(r.step)] = _kept(value, False)
        _failed(run, skills, told, why or "error", check)
        return
    names_exit = name == "done" or (own is not None and not _holds(own, {"exit": "failed"}, r, []))
    if own is not None and ruled and not (_holds(own, value, r, told) and names_exit):
        r.results[str(r.step)] = _kept(value, False)
        # Only a done ending takes a hold here: every tool of the sub-skill was then free, so the check can be run
        # again. An exit can be called before the sub-skill reaches a tool another skill holds, and a hold taken
        # then could lock the two skills for good.
        if name == "done":
            _hold(run, skills)
        _failed(run, skills, told, why or "check", check if why else own.text)
        return
    _passed(run, skills, value, told)


_BECAUSE: dict[EndedWhy, str] = {
    "denied": " because a person rejected its action",
    "error": " because the step could not be done",
    "held": " because another skill holds the step's tool",
}


def ending(ended: EndedSkill) -> str:
    """What the model is told about a skill that ended any way but done: the exit, the step, the reason the record
    holds, and whether it may start again in this reply."""
    because = (
        f" because its check did not pass ({ended.check})" if ended.check else _BECAUSE.get(ended.why or "exit", "")
    )
    means = f" {ended.ended} means: {ended.meaning}" if ended.meaning else ""
    closed = (
        " It cannot start again in this reply; it can after the person's next message."
        if ended.in_reply and ended.why in FINAL
        else ""
    )
    return (
        f"{ended.name} ended as {ended.ended} on step {ended.at_step}{because}.{means}{closed} Do not say its action "
        "was done or will be done. Tell the person what was not done, and why."
    )


def final(run: SkillRunState, skill_id: str) -> EndedSkill | None:
    """The ending that keeps the skill from starting again in this reply: one the kernel made in it (`FINAL`). The
    person's next message, or their pick from the menu, starts it as usual."""
    return next((h for h in reversed(run.history) if h.skill_id == skill_id and h.in_reply and h.why in FINAL), None)


def _again(run: SkillRunState, skill_id: str, slug: str) -> str:
    """How a held tool comes back: its holder starts again and passes the step, which a reply the kernel ended the
    holder in does not allow."""
    if final(run, skill_id) is not None:
        return f"{slug} cannot start again in this reply, so tell the person; it can after their next message."
    return f"start {slug} again."


def said(before: SkillRunState, after: SkillRunState) -> str:
    """What the model is told after an event, from where the record was and where it is."""
    was = before.running
    now_ = after.running
    if now_ is None:
        ended = after.history[-1]
        if ended.ended == "done":
            return f"{ended.name} is done."
        return ending(ended)
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
            # The judge reads the result as the tool gave it: what the model is shown may be a shaped summary.
            got = f" The tool returned {json.dumps(res.value)}." if res.value is not None else ""
            return (
                f"Now confirm: {step.check.text}{got} Call step_done only if that holds for this result; if it "
                "does not, say so and do not go on."
            )
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


def changes(name: str, access: str | None) -> bool:
    """Whether a step's tool is one that changes something: any tool that is not a read (a write, a workflow), and
    any other agent a step hands to, whatever its access says. A tool whose access is not known is taken as one. The
    one test behind the tools a skill owns (`owned`) and the steps a save asks a rule check of."""
    return hands_to_agent(name) or (access or "write") != "read"


def owned(skills: Sequence[Skill], access: Mapping[str, str]) -> dict[str, list[str]]:
    """The tools reachable only through a step, each with the slugs of the skills whose steps run it: every tool a
    step of an attached skill runs that changes something (`changes`), and every read a builder locked to its step.
    `access` is each granted tool's access by name."""
    out: dict[str, list[str]] = {}
    for s in skills:
        locked = s.program.locked() if s.program is not None else set[str]()
        for name in sorted(s.program.targets()) if s.program is not None else ():
            if name in locked or changes(name, access.get(name)):
                out.setdefault(name, []).append(s.slug)
    return out


def barred(
    run: SkillRunState,
    skills: Sequence[Skill],
    tool: str,
    *,
    owned: Mapping[str, Sequence[str]],
    stopped: Mapping[str, Sequence[str]],
    always: Sequence[str] = (),
) -> str | None:
    """Why `tool` may not be used now, in words for the model; None when it may. The one answer to "may this tool be
    called", asked when the tools are offered, when they are searched and again when one is called, so a call sent in
    the same model step as the one that starts or leaves a skill gets the answer for where the record then stands.

    In order: a tool a skill stopped in this reply keeps (`stopped`, by skill id) and a tool another skill holds stay
    out even as the current step's tool, so a write cannot run through a skill that skips the check that failed.
    The current step's tool may be called. A tool of another step of the running skill waits for its step. A tool a
    skill owns (`owned`) runs only as that skill's step, so its checks cannot be skipped by not starting it. And
    while a step names its tool, that tool and those in `always` are the only ones."""
    r = run.running
    if (sid := next((k for k, tools in stopped.items() if tool in tools), None)) is not None:
        last = next((h for h in reversed(run.history) if h.skill_id == sid), None)
        how = f"{last.name} ended as {last.ended}" if last is not None else "a skill that calls it was stopped"
        return f"{tool} is not available for the rest of this reply: {how}."
    for hold in run.holds:
        if tool in hold.tools and (r is None or r.skill_id != hold.skill_id):
            why = f"a person denied a call of {hold.slug}" if hold.denied else f"{hold.slug} failed its check"
            return f"{tool} is held because {why}; {_again(run, hold.skill_id, hold.slug)}"
    current = target(run)
    if tool == current:
        return None
    if r is not None and tool in _tools(r, skills):
        return f"{tool} belongs to another step of {r.name}. Do the current step first."
    if tool in owned:
        slugs = " or ".join(owned[tool])
        return (
            f"{tool} runs only as a step of {slugs}. Start that skill with switch_skill; it reaches {tool} at its step."
        )
    if current is not None and tool not in always:
        return f"The current step calls {current}. Do only this step."
    return None


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
        _failed(run, skills, told, "error")
    elif step.check is None:
        _passed(run, skills, output, told)
    elif _is_rule(step.check):
        if _holds(step.check, output, f, told):
            _passed(run, skills, output, told)
        else:
            f.results[key] = _kept(output, False)
            _hold(run, skills)
            _failed(run, skills, told, "check", step.check.text)
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
        _hold(run, skills)
        _failed(run, skills, told, "check", step.check.text)
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
        _sub_ended(run, skills, name, clean, told, why=None if name == "done" else "exit")
    else:
        _end(run, name, skills, clean, why="exit")
    _stop_if_held(run, skills, told)
    return Moved(run, " ".join([*told, said(before, run)]))


def denied(run: SkillRunState, skills: Sequence[Skill]) -> SkillRunState:
    """A person rejected the current step's call: the skill ends as failed at once, and holds the denied tool with
    the tools of its later steps."""
    if run.running is None:
        return run
    run = run.model_copy(deep=True)
    _hold(run, skills, denied=True)
    _end(run, "failed", skills, why="denied")
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
    why = f"{tool} is held for the rest of this reply because {slug} ended as {how}; {_again(run, holder, slug)}"
    _end(run, "failed", skills, holds=False, why="held")
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
