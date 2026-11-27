"""Automatic mode and the loop kinds, one test per failure mode of the acceptance table in
docs/design/agents-v2/automatic-mode-and-loop-kinds.md: a lookup that plans, a workspace the
spec lacks, a `single` agent that plans, and a quality bar that never stops."""

from __future__ import annotations

from typing import Any

from ops_agent_kernel import judge
from ops_agent_kernel.events import KernelEvent, ModeChanged, TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts
from ops_agent_kernel.testing import tool_names
from ops_agent_kernel.types import LoopSettings, ToolGrant, TurnRequest, TurnResult
from ops_service_kit.http import Json
from tests.conftest import last_user_text, model_on, scripted, scripted_model
from tests.unit.test_kernel import HOLD, LIMITS, SETTINGS, FixedKnowledge, RecordingTools

HELPER = ToolGrant(
    "agent__ag_credit_policy",
    "agents",
    "Ask Credit Policy",
    "read",
    {"type": "object", "properties": {"question": {"type": "string"}}},
)
WORKSPACE = ToolGrant("run_command", "workspace", "Run a command in the workspace", "write", {"type": "object"})


async def run(req: TurnRequest, ports: KernelPorts) -> tuple[list[KernelEvent], TurnResult]:
    events = [e async for e in run_turn(req, ports)]
    last = events[-1]
    assert isinstance(last, TurnFinished)
    return events, last.result


async def test_a_lookup_is_answered_directly_in_one_model_request() -> None:
    # The seeded lookup: the daily wire limit, answered from the knowledge block.
    req = TurnRequest("t1", "th1", SETTINGS, [], user_turn="What is the daily wire limit?", kb_ids=["kb_people"])
    ports = KernelPorts(model=scripted_model(), tools=RecordingTools(), knowledge=FixedKnowledge([LIMITS]))
    events, result = await run(req, ports)
    assert [m.mode for m in result.modes] == ["direct"]
    assert [e.mode for e in events if isinstance(e, ModeChanged)] == ["direct"]
    assert result.usage.requests == 1


def offering(seen: list[set[str]]) -> Any:
    def script(messages: list[Json], tools: list[Json]) -> str:
        seen.append(tool_names(tools))
        return "Done."

    return script


async def test_with_no_sandbox_in_the_spec_the_turn_holds_no_workspace_tool() -> None:
    seen: list[set[str]] = []
    req = TurnRequest("t1", "th1", SETTINGS, [HOLD, WORKSPACE], user_turn="Reconcile the file")
    await run(req, KernelPorts(model=model_on(offering(seen)), tools=RecordingTools(), knowledge=FixedKnowledge([])))
    assert "place_wire_hold" in seen[0] and "run_command" not in seen[0]


async def test_a_single_agent_is_offered_no_plan_and_no_helper() -> None:
    seen: list[set[str]] = []
    req = TurnRequest(
        "t1", "th1", SETTINGS, [HOLD, HELPER], user_turn="Hold wire W-88213", loop=LoopSettings(kind="single")
    )
    _, result = await run(
        req, KernelPorts(model=model_on(offering(seen)), tools=RecordingTools(), knowledge=FixedKnowledge([]))
    )
    assert "place_wire_hold" in seen[0]
    assert not {"plan", HELPER.name} & seen[0]
    assert [(m.mode, m.fixed) for m in result.modes] == [("direct", True)]


async def test_a_judge_that_always_fails_stops_after_max_rounds_and_says_the_bar_was_not_met() -> None:
    judged: list[str] = []

    def script(messages: list[Json], tools: list[Json]) -> Any:
        text = last_user_text(messages)
        if text.startswith(judge.PROMPT_HEAD):
            judged.append(text)
        return scripted(messages, tools)

    # The rubric quotes words no answer holds, so the scripted judge always says no (conftest.judged).
    loop = LoopSettings(rubric='The reply says "refund approved".', max_rounds=2)
    req = TurnRequest("t1", "th1", SETTINGS, [], user_turn="Where is my refund?", loop=loop)
    _, result = await run(
        req, KernelPorts(model=model_on(script), tools=RecordingTools(), knowledge=FixedKnowledge([]))
    )
    assert len(judged) == 3
    assert result.status == "completed" and result.bar_met is False
