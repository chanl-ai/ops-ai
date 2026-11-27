"""Automatic mode: which way of working a turn used, named from the first use of each, and the rule that a change runs
as a plan (docs/design/agents-v2/automatic-mode-and-loop-kinds.md, "Automatic mode").

The model chooses as it goes; the kernel names the mode. `direct` is named when the first model step ends and nothing
else was used; `plan`, `helpers` and `sandbox` when the plan tool accepts a plan, a helper is first asked, or a
workspace tool is first called, each with the call's `why` argument as its reason. A turn can use several.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ops_service_kit.http import Json, JsonList
from ops_service_kit.narrow import json_list, json_object

from .pii import mask
from .types import LoopSettings, ModeName, ModeStep, ToolGrant

DIRECT_REASON = "Answered without a plan, a helper or the workspace."
NO_REASON = "No reason given."
WHY_CHARS = 200
PLAN_FIRST = "Write the plan first with the plan tool, then call this again."
NO_WORKSPACE = "This agent has no workspace."
# The server a helper's grant (`agent__<id>`) and a workspace tool are offered under.
HELPERS_SERVER = "agents"
WORKSPACE_SERVER = "workspace"
WHY: Json = {"type": "string", "maxLength": WHY_CHARS, "description": "In one sentence, why this request needs it"}
# The kinds whose turns hold the plan tool, and so must show a plan before a change.
PLANNING = ("auto", "plan_execute", "supervisor", "evaluator", "long_running")


def with_why(schema: Json) -> Json:
    """A tool's input schema with the required `why` argument that names the mode it starts."""
    props: Json = {**json_object(schema.get("properties")), "why": WHY}
    required: JsonList = [*json_list(schema.get("required")), "why"]
    return {**schema, "properties": props, "required": required}


def reason_of(arguments: Json) -> str:
    """The `why` a call gave, cut to its limit and masked like shown text; the model never reads it back."""
    return mask(str(arguments.get("why") or "").strip())[:WHY_CHARS] or NO_REASON


def is_helper(grant: ToolGrant) -> bool:
    return grant.server == HELPERS_SERVER


def is_workspace(grant: ToolGrant) -> bool:
    return grant.server == WORKSPACE_SERVER


def needs_plan(loop: LoopSettings, grant: ToolGrant) -> bool:
    """Whether a call of `grant` is refused until the turn has a plan: a change, in a kind that plans."""
    return loop.kind in PLANNING and grant.access != "read" and not is_helper(grant)


@dataclass
class Modes:
    """The modes a turn named, in order, each once."""

    fixed: bool
    steps: list[ModeStep] = field(default_factory=list[ModeStep])

    def first(self, mode: ModeName, reason: str, at_step: int) -> ModeStep | None:
        """The step to emit when `mode` is used for the first time this turn; None when it was named already."""
        if any(s.mode == mode for s in self.steps):
            return None
        step = ModeStep(mode, reason, at_step, self.fixed)
        self.steps.append(step)
        return step

    def direct(self, at_step: int) -> ModeStep | None:
        """`direct`, when the first model step ended with no other mode used."""
        return None if self.steps else self.first("direct", DIRECT_REASON, at_step)
