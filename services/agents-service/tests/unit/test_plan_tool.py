"""The plan tool, by failure mode: two steps doing at once, a done step reopened or renamed, endless replanning, a
step that spends the whole turn's budget, a plan title that shows personal data, a plan lost at a pause, a finished
plan left open, and a plan an earlier turn left open forgotten by the next."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agent_kernel import plan as planner
from ops_agent_kernel.events import ToolOutput, TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.types import (
    AgentSettings,
    Interrupt,
    PendingCall,
    PromptFragment,
    ToolGrant,
    TurnRequest,
    TurnResult,
)
from ops_agents.activities.catalog import load_catalog
from ops_agents.api.chat_history import history_entry
from ops_agents.api.chat_threads import AssistantBuilder
from ops_agents.graphs.common import interrupt_from_state, interrupt_to_state
from ops_contracts.chat import ChatMessage
from tests.conftest import SEED

READ = ToolGrant(
    "find_cases", "Ops AI", "Find cases", "read", {"type": "object", "properties": {"q": {"type": "string"}}}
)
SETTINGS = AgentSettings("ag_ops", 1, [PromptFragment("You help.")], "m", max_tool_calls=1, max_steps=4)


def steps(*statuses: str) -> list[dict[str, Any]]:
    return [{"title": f"Step {i + 1}", "status": s} for i, s in enumerate(statuses)]


def plan_call(*statuses: str, **more: Any) -> ToolCallPart:
    return ToolCallPart("plan", {"title": "Check the loan files", "steps": steps(*statuses), **more})


class Reads:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        self.calls.append(tool)
        return ToolOutcome(True, {"cases": [{"title": "Renewal"}]})


class NoKnowledge:
    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Any]:
        return []


def scripted(*responses: list[Any] | str) -> tuple[FunctionModel, list[str]]:
    """A model that answers each request with the next response: a list of tool calls, or text. Records the system
    instructions it was sent."""
    queue = list(responses)
    seen: list[str] = []

    def next_parts(info: AgentInfo) -> list[Any]:
        seen.append(str(info.instructions or ""))
        r = queue.pop(0) if queue else "Done."
        return [TextPart(r)] if isinstance(r, str) else r

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=next_parts(info))

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        parts = next_parts(info)
        if isinstance(parts[0], TextPart):
            yield parts[0].content
        else:
            yield {i: DeltaToolCall(name=p.tool_name, json_args=json.dumps(p.args)) for i, p in enumerate(parts)}

    return FunctionModel(respond, stream_function=stream), seen


async def run(model: FunctionModel, req: TurnRequest) -> tuple[TurnResult, list[Any]]:
    events = [e async for e in run_turn(req, KernelPorts(model=model, tools=Reads(), knowledge=NoKnowledge()))]
    last = events[-1]
    assert isinstance(last, TurnFinished)
    return last.result, events


def test_one_step_at_a_time_forward_only_and_finished_titles_kept() -> None:
    before = {"title": "t", "steps": steps("done", "doing", "todo")}
    assert "One step" in str(
        planner.check(None, {"title": "t", "steps": steps("doing", "doing", "todo")}, replan=False, replans=0)
    )
    assert "cannot go back" in str(
        planner.check(before, {"title": "t", "steps": steps("done", "todo", "todo")}, replan=False, replans=0)
    )
    renamed = {"title": "t", "steps": [{"title": "Other", "status": "done"}, *steps("done", "doing", "todo")[1:]]}
    assert "keeps its title" in str(planner.check(before, renamed, replan=False, replans=0))
    assert (
        planner.check(before, {"title": "t", "steps": steps("done", "done", "doing")}, replan=False, replans=0) is None
    )


def test_a_third_replan_is_refused() -> None:
    before = {"title": "t", "steps": steps("done", "blocked", "todo")}
    again = {"title": "t", "steps": steps("done", "doing", "todo")}
    assert planner.check(before, again, replan=True, replans=1) is None
    assert "finish with what you have" in str(planner.check(before, again, replan=True, replans=2))


def test_a_step_title_is_masked_as_reply_text_is() -> None:
    plan, _ = planner.given({"title": "Card 4111 1111 1111 1111", "steps": steps("doing", "todo", "todo")})
    assert plan is not None and "4111" not in plan["title"], plan


async def test_each_finished_step_gets_its_own_budget_and_the_done_plan_reads_did_n_steps() -> None:
    # A plan's second step read nothing: the first step had spent the turn's one tool call.
    model, _ = scripted(
        [plan_call("doing", "todo", "todo"), ToolCallPart("find_cases", {"q": "open conditions"})],
        [plan_call("done", "doing", "todo"), ToolCallPart("find_cases", {"q": "renewals"})],
        [plan_call("done", "done", "done")],
        "Two files have open conditions and a renewal this month.",
    )
    result, events = await run(model, TurnRequest("t1", "r1", SETTINGS, [READ], user_turn="Which loan files?"))
    assert result.stop_reason == "final", result
    reads = [r for r in result.tool_calls if r.tool == "find_cases"]
    assert [r.status for r in reads] == ["ok", "ok"], reads
    last = [e.call for e in events if isinstance(e, ToolOutput) and e.call.tool == "plan"][-1]
    assert last.view is not None and last.view["part"]["hint"]["title"] == "Did 3 steps"
    assert [s["state"] for s in last.view["part"]["data"]] == ["done", "done", "done"]


async def test_a_turn_that_stops_with_steps_left_marks_the_step_blocked() -> None:
    model, _ = scripted([plan_call("doing", "todo", "todo")], "Connect Salesforce to go on.")
    result, events = await run(model, TurnRequest("t1", "r1", SETTINGS, [READ], user_turn="Which loan files?"))
    last = [e.call for e in events if isinstance(e, ToolOutput) and e.call.tool == "plan"][-1]
    assert last.view is not None
    assert [s["state"] for s in last.view["part"]["data"]] == ["failed", "pending", "pending"]
    assert last.view["part"]["data"][0]["title"].endswith("waiting for you")
    assert planner.from_part(last.view["part"]) is not None and result.stop_reason == "final"


async def test_a_plan_left_open_goes_on_in_the_next_turn() -> None:
    carried = {"title": "Check the loan files", "steps": steps("done", "blocked", "todo")}
    model, seen = scripted([plan_call("done", "doing", "todo")], [plan_call("done", "done", "done")], "Finished.")
    req = TurnRequest(
        "t2", "r2", SETTINGS, [READ], user_turn="I connected Salesforce. Please go ahead.", carried_plan=carried
    )
    result, _ = await run(model, req)
    assert "## Plan in progress: Check the loan files" in seen[0], seen[0]
    plans = [r for r in result.tool_calls if r.tool == "plan"]
    assert [r.status for r in plans] == ["ok", "ok"], plans


def test_the_chat_keeps_one_plan_part_on_top_and_hands_an_open_plan_to_the_next_turn() -> None:
    builder = AssistantBuilder(load_catalog(SEED), ChatMessage(id="m1", role="assistant", content="", at="t"))
    read = {"id": "c1", "tool": "find_cases", "server": "Ops AI", "input": {}, "status": "ok", "output": [{"a": 1}]}
    table = {"type": "widget", "id": "", "shape": "rows", "data": [{"a": 1}]}
    builder.apply("tool_call", {**read, "view": {"part": table}})
    for i, statuses in enumerate((("doing", "todo", "todo"), ("done", "blocked", "todo"))):
        drawn = planner.part({"title": "Check", "steps": steps(*statuses)})
        builder.apply(
            "tool_call",
            {"id": f"p{i}", "tool": "plan", "server": "kernel", "input": {}, "status": "ok", "view": {"part": drawn}},
        )
    parts = builder.message.parts or []
    assert [p.id for p in parts] == ["wp_plan", "wp_c1"], [p.id for p in parts]
    carried = history_entry(builder.message)
    assert carried["plan"]["steps"][1]["status"] == "blocked" and "reads" in carried, carried
    # An approval pause keeps the plan through the run's saved state.
    call = PendingCall("c", "k", "a", "t", "s", "write", {}, "h")
    kept = Interrupt(
        "i", "approval", "Approval", call, b"[]", [], {"title": "Check", "steps": steps("done", "blocked", "todo")}
    )
    assert interrupt_from_state(interrupt_to_state(kept)).plan == kept.plan
