"""The built-in tools a skill with steps is driven by: `switch_skill` starts one (and ends the one running, so
nothing stacks), `step_done` says the current step is done, `exit` ends the skill with one of its exits. No port is
behind them. They are counted on their own (`limit`), not against the agent's cap on kernel tools: a skill of four
steps needs four `step_done` calls in one reply.
"""

from __future__ import annotations

from collections.abc import Sequence

from ops_contracts.skill_run import SkillRunState
from ops_service_kit.http import Json, JsonList
from ops_service_kit.narrow import json_object

from . import steps
from .steps import Moved
from .types import Skill, ToolGrant

STEP_DONE = "step_done"
EXIT = "exit"
SWITCH = "switch_skill"
NAMES = (STEP_DONE, EXIT, SWITCH)


def stepped(skills: Sequence[Skill]) -> list[Skill]:
    """The skills that run step by step."""
    return [s for s in skills if s.program is not None and s.program.steps]


def limit(skills: Sequence[Skill]) -> int:
    """How many calls to these tools one reply may make: twice every step the agent's skills hold, and four."""
    return 4 + 2 * sum(len(s.program.steps) for s in skills if s.program is not None)


def needs(skill: Skill, missing: Sequence[str]) -> str:
    """What is said when `skill` is not started for want of the inputs `missing`."""
    return (
        f"{skill.name} needs {', '.join(missing)} before it can start. Ask the person for "
        f"{'it' if len(missing) == 1 else 'them'}, then call {SWITCH} with the slug {skill.slug} and those inputs."
    )


def _asks(skills: Sequence[Skill]) -> str:
    """The inputs each skill requires, for the description of switch_skill's `inputs`."""
    lines = [
        f"{s.slug} requires {', '.join(names)}" for s in skills if (names := [i.name for i in s.inputs if i.required])
    ]
    return f"What the skill needs to start, by name{': ' + '; '.join(lines) if lines else ''}"


def grants(skills: Sequence[Skill]) -> list[ToolGrant]:
    """The three tools, for an agent that holds a skill with steps; none otherwise."""
    held = stepped(skills)
    slugs: JsonList = [s.slug for s in held]
    if not slugs:
        return []
    return [
        ToolGrant(
            SWITCH,
            "platform",
            "Starts one of your skills that run step by step, by its slug, when the request matches its use-when "
            "line. A skill already running ends first: only one runs at a time. A skill ended in this reply because "
            "a check did not pass, a person rejected its action or a step could not be done does not start again "
            "until the person's next message.",
            "read",
            {
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "enum": slugs},
                    "inputs": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": _asks(held),
                    },
                    "reason": {"type": "string", "maxLength": 300},
                },
                "required": ["slug"],
            },
        ),
        ToolGrant(
            STEP_DONE,
            "platform",
            "Says the current step of the running skill is done. Refused while the step's tool has not run, and "
            "for a step whose check runs on the tool result.",
            "read",
            {"type": "object", "properties": {"summary": {"type": "string", "maxLength": 300}}},
        ),
        ToolGrant(
            EXIT,
            "platform",
            "Ends the running skill with one of its exits. done is accepted only after the last step has passed; "
            "failed, or an exit the skill lists, at any step.",
            "read",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "returns": {"type": "object", "description": "The skill's results, by name"},
                    "reason": {"type": "string", "maxLength": 300},
                },
                "required": ["name"],
            },
        ),
    ]


def handle(name: str, run: SkillRunState, skills: Sequence[Skill], arguments: Json) -> Moved:
    """One call to a step tool: the record after it and what the model is told."""
    if name == STEP_DONE:
        return steps.step_done(run, skills)
    if name == EXIT:
        return steps.leave(run, skills, str(arguments.get("name") or ""), json_object(arguments.get("returns")))
    slug = str(arguments.get("slug") or "")
    skill = next((s for s in stepped(skills) if s.slug == slug), None)
    if skill is None:
        return Moved(run, f"No skill with steps named {slug} is attached to this agent.", ok=False)
    running = run.running
    if running is not None and running.skill_id == skill.skill_id:
        return Moved(run, f"{skill.name} is already running, on step {running.step}. Go on with that step.", ok=False)
    if (ended := steps.final(run, skill.skill_id)) is not None:
        # The kernel ended it in this reply: the ending stands until the person's next message.
        return Moved(run, steps.ending(ended), ok=False)
    inputs = {k: str(v) for k, v in json_object(arguments.get("inputs")).items()}
    if missing := steps.missing_inputs(skill, inputs):
        return Moved(run, needs(skill, missing), ok=False)
    told: list[str] = []
    started = steps.start(run, skill, skills, by="model", inputs=inputs, told=told)
    return Moved(started, " ".join([*told, steps.said(run, started)]))
