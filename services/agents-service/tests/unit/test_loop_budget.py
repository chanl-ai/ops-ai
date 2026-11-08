"""The loop budget: the kernel's own tools capped together at three a turn, and the last step kept for the answer.

One test per way it breaks: a tool-happy model ends the turn with no answer (F7); search_tools spends every step;
present past the built-in cap breaks the turn instead of answering (F8); a gated write on the step before the last is
lost (F9)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import BUILTIN_LIMIT, run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.types import AgentSettings, Passage, PromptFragment, ToolGrant, TurnRequest, TurnResult

CASES = ToolGrant(
    "find_cases", "ops", "Find cases", "read", {"type": "object", "properties": {"search": {"type": "string"}}}
)
HOLD = ToolGrant(
    "place_wire_hold",
    "Payments Hub",
    "Hold a wire",
    "write",
    {"type": "object", "properties": {"id": {"type": "string"}}},
)
ANSWER = "Three cases are open."


def settings(steps: int = 4) -> AgentSettings:
    return AgentSettings("ag_ops", 1, [PromptFragment("You are Ops Assistant.")], "test-model", 10, steps)


class Tools:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        self.calls.append(tool)
        return ToolOutcome(True, {"cards": [], "summary": f"{len(self.calls)} case(s)"})


class NoKnowledge:
    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Passage]:
        return []


def told_to_answer(messages: list[ModelMessage]) -> bool:
    """The last tool result is the built-in cap's instruction to answer in text."""
    back = [p for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)]
    return bool(back) and "answer in text" in json.dumps(back[-1].content)


def eager(pick: Any) -> FunctionModel:
    """A model that calls whatever `pick(offered names, messages)` returns while it is offered, else answers, and
    answers once told to; one that ignores the instruction is the step-limit case (tests/api/test_turn_limits.py)."""

    def choose(offered: list[str], messages: list[ModelMessage]) -> Any:
        return None if told_to_answer(messages) else pick(offered, messages)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        offered = [t.name for t in info.function_tools]
        call = choose(offered, messages)
        if call is None:
            return ModelResponse(parts=[TextPart(ANSWER)])
        name, args = call
        return ModelResponse(parts=[ToolCallPart(name, args)])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        offered = [t.name for t in info.function_tools]
        call = choose(offered, messages)
        if call is None:
            yield ANSWER
            return
        name, args = call
        yield {0: DeltaToolCall(name=name, json_args=json.dumps(args))}

    return FunctionModel(respond, stream_function=stream)


async def run(req: TurnRequest, model: FunctionModel, tools: Tools) -> TurnResult:
    events = [e async for e in run_turn(req, KernelPorts(model=model, tools=tools, knowledge=NoKnowledge()))]
    last = events[-1]
    assert isinstance(last, TurnFinished)
    return last.result


async def test_a_tool_happy_model_answers_on_the_last_step() -> None:
    # F7: a model that reads while any read is offered spent all its steps and ended on the step-limit notice.
    tools = Tools()
    # A new search each step: the same call twice is answered from the first and closes the tools on its own.
    model = eager(lambda offered, m: ("find_cases", {"search": f"s{len(m)}"}) if "find_cases" in offered else None)
    result = await run(TurnRequest("t1", "th1", settings(3), [CASES], user_turn="Everything open"), model, tools)
    assert result.stop_reason == "final", result
    assert result.text == ANSWER
    assert len(tools.calls) == 2


async def test_search_tools_stops_after_three_calls_and_the_turn_answers() -> None:
    # The step budget went on free search_tools calls (eight in one turn) and the reply was the step-limit notice.
    tools = Tools()
    model = eager(lambda offered, _m: ("search_tools", {"query": "apps"}) if "search_tools" in offered else None)
    result = await run(TurnRequest("t1", "th1", settings(8), [CASES], user_turn="Which apps?"), model, tools)
    searches = [c for c in result.tool_calls if c.tool == "search_tools"]
    assert result.text == ANSWER and result.stop_reason == "final", result
    assert [c.status for c in searches] == ["ok", "ok", "ok", "error"]
    assert searches[-1].output == {"error": BUILTIN_LIMIT.format(cap=3)}


async def test_present_past_the_builtin_cap_answers_in_text() -> None:
    # F8: present after the cap is refused with an instruction and the turn still completes with an answer.
    def pick(offered: list[str], messages: list[ModelMessage]) -> tuple[str, dict[str, Any]] | None:
        made = sum(1 for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolCallPart))
        if made < 3 and "search_tools" in offered:
            return "search_tools", {"query": "cases"}
        if "present" in offered:
            return "present", {"shape": "rows", "data": [{"case": "C-1"}]}
        return None

    tools = Tools()
    result = await run(TurnRequest("t1", "th1", settings(8), [CASES], user_turn="Cases"), eager(pick), tools)
    shown = [c for c in result.tool_calls if c.tool == "present"]
    assert result.text == ANSWER and result.status == "completed", result
    assert [c.status for c in shown] == ["error"] and shown[0].view is None


async def test_a_write_on_the_step_before_the_last_still_pauses_for_approval() -> None:
    # F9: closing tools at the last step must not lose a gated write asked for on the step before it.
    tools = Tools()
    model = eager(lambda offered, _m: ("place_wire_hold", {"id": "W-1"}) if "place_wire_hold" in offered else None)
    result = await run(TurnRequest("t1", "th1", settings(2), [HOLD], user_turn="Hold W-1"), model, tools)
    assert result.status == "interrupted" and result.interrupt is not None, result
    assert tools.calls == []
