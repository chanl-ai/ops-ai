"""The fixed loop kinds an agent can run (automatic-mode-and-loop-kinds.md, "The seven fixed kinds"): what each is
called and when to use it, its own settings as JSON Schema, what it requires of the install, and which of the turn's
tools it is given. The catalogue is the one `GET /v1/agents/loops` answers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ops_service_kit.http import Json, JsonValue

from . import modes
from .types import LoopKind, LoopSettings, ToolGrant

Requirement = str  # "agents", "sandbox", "workflow", "rubric"


@dataclass(frozen=True)
class Kind:
    kind: LoopKind
    name: str
    description: str
    when_to_use: str
    settings_schema: Json
    requires: tuple[Requirement, ...] = ()
    # Built in a later release: listed, never runnable here.
    later: str | None = None


def _schema(**props: JsonValue) -> Json:
    return {"type": "object", "properties": dict(props), "additionalProperties": False}


_INT: Json = {"type": "integer", "minimum": 0}
_BOOL: Json = {"type": "boolean"}

KINDS: tuple[Kind, ...] = (
    Kind(
        "auto",
        "Automatic",
        "One agent decides as it goes whether a request needs a plan, a helper agent or nothing more.",
        "The default. Most agents: lookups are answered at once, and changes are planned first.",
        _schema(replans=_INT),
    ),
    Kind(
        "single",
        "Single step",
        "The agent answers with its own tools only. It never plans and never asks another agent.",
        "A narrow agent whose every request is a lookup or one action.",
        _schema(),
    ),
    Kind(
        "plan_execute",
        "Plan, then carry out",
        "The agent writes a plan first, then works through it step by step.",
        "Requests that always take several steps, where the person should see the plan.",
        _schema(replans=_INT, showPlan=_BOOL, reviewPlan=_BOOL),
    ),
    Kind(
        "supervisor",
        "Supervisor",
        "The agent plans and asks its helper agents, each answering on its own thread.",
        "Requests that need the knowledge or tools of several specialist agents.",
        _schema(),
        requires=("agents",),
    ),
    Kind(
        "swarm",
        "Hand-overs",
        "The agent hands the conversation to another agent, with shared notes.",
        "Conversations that move between specialists, such as intake and then a desk.",
        _schema(maxHandoffs={"type": "integer", "minimum": 1, "maximum": 10}),
        requires=("agents",),
        later="Hand-overs between agents arrive in a later build.",
    ),
    Kind(
        "workflow",
        "Fixed workflow",
        "The message starts a run of a published workflow, and its result is the reply.",
        "A process that must run the same steps every time.",
        _schema(workflow={"type": "string"}, input={"type": "object", "additionalProperties": {"type": "string"}}),
        requires=("workflow",),
        later="The workflow kind runs its workflow in a later release.",
    ),
    Kind(
        "evaluator",
        "Checked answer",
        "As automatic, and each answer is judged against a rubric and sent back when it falls short.",
        "Answers that must meet a written quality bar.",
        _schema(rubric={"type": "string"}, judge={"type": "string"}, maxRounds={"type": "integer", "minimum": 1}),
        requires=("rubric",),
    ),
    Kind(
        "long_running",
        "Long running",
        "As automatic, with a workspace, run as a background job the chat can re-attach to.",
        "Work that takes minutes to hours, such as reconciling a large file.",
        _schema(maxMinutes={"type": "integer", "minimum": 1}, background=_BOOL),
        requires=("sandbox",),
        later="Long-running turns arrive in release 1.5.0.",
    ),
)


def kind(name: str) -> Kind:
    return next(k for k in KINDS if k.kind == name)


def has_plan(loop: LoopSettings) -> bool:
    """Whether the kind's turn holds the plan tool."""
    return loop.kind in modes.PLANNING


def offered(loop: LoopSettings, tools: list[ToolGrant]) -> list[ToolGrant]:
    """The spec's tools a turn of this kind is given. Helpers only to kinds that ask them; workspace tools only when the
    spec has a sandbox; a helper or workspace tool gets the required `why` argument that names its mode."""
    out: list[ToolGrant] = []
    for t in tools:
        if modes.is_helper(t):
            if loop.kind not in ("auto", "supervisor", "evaluator", "long_running", "plan_execute"):
                continue
        elif modes.is_workspace(t):
            if not loop.sandbox or loop.kind in ("single", "workflow"):
                continue
        else:
            out.append(t)
            continue
        out.append(_why(t))
    return out


def _why(t: ToolGrant) -> ToolGrant:
    return replace(t, input_schema=modes.with_why(t.input_schema))
