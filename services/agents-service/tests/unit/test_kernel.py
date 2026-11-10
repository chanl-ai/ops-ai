"""One test per kernel failure mode: wrong citations, a gated write that runs before approval, a resume that runs
different input or a new key, a rejection the model never hears, and assembly errors reaching the model."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agent_kernel.events import CitationsReady, KernelEvent, TextDelta, ToolOutput, TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.types import (
    AgentSettings,
    Passage,
    PromptFragment,
    Resume,
    ToolGrant,
    TurnRequest,
    TurnResult,
)
from ops_service_kit.ids import input_hash
from tests.conftest import looping_model, scripted_model

HOLD = ToolGrant(
    "place_wire_hold",
    "Payments Hub",
    "Hold a wire",
    "write",
    {
        "type": "object",
        "properties": {"wireId": {"type": "string"}, "hours": {"type": "integer"}, "reason": {"type": "string"}},
    },
)
SETTINGS = AgentSettings("ag_fraud", 7, [PromptFragment("You help Fraud Operations.")], "test-model")
LIMITS = Passage(
    "doc_wire_limits",
    "Wire Transfer Policy",
    "4.2 Daily limits",
    "v6",
    "Personal daily wire limit $25,000.",
    "kb_people",
)
HOLDS = Passage(
    "doc_wire_holds", "Wire Transfer Policy", "5.1 New-payee holds", "v6", "New payee wires held 24 hours.", "kb_people"
)


class RecordingTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], str, str | None]] = []

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        self.calls.append((tool, arguments, key, approval_token))
        return ToolOutcome(True, {"status": "completed", "reference": "NB-1"})


class FixedKnowledge:
    def __init__(self, passages: list[Passage]) -> None:
        self.passages = passages

    async def search(self, query: str, kb_ids: list[str]) -> list[Passage]:
        return self.passages


async def run(req: TurnRequest, ports: KernelPorts) -> tuple[list[KernelEvent], TurnResult]:
    events = [e async for e in run_turn(req, ports)]
    last = events[-1]
    assert isinstance(last, TurnFinished)
    return events, last.result


def ports(tools: RecordingTools, passages: list[Passage] | None = None) -> KernelPorts:
    return KernelPorts(model=scripted_model(), tools=tools, knowledge=FixedKnowledge(passages or []))


async def test_only_cited_passages_become_citations() -> None:
    req = TurnRequest("t1", "th1", SETTINGS, [], user_turn="What is the daily wire limit?", kb_ids=["kb_people"])
    events, result = await run(req, ports(RecordingTools(), [LIMITS, HOLDS]))
    assert result.status == "completed"
    assert [c.n for c in result.citations] == [1]
    assert result.citations[0].passage.document_id == "doc_wire_limits"
    assert any(isinstance(e, CitationsReady) for e in events)


async def test_gated_write_ends_turn_without_running() -> None:
    tools = RecordingTools()
    req = TurnRequest("t1", "th1", SETTINGS, [HOLD], user_turn="Hold wire W-88213")
    _, result = await run(req, ports(tools))
    assert result.status == "interrupted"
    assert tools.calls == []
    assert result.interrupt is not None
    pending = result.interrupt.pending_call
    assert pending.input["wireId"] == "W-88213"
    assert pending.input_hash == input_hash(pending.input)
    assert pending.key.startswith("th1:t1:")


async def test_a_write_declared_to_run_at_once_runs_without_a_pause() -> None:
    # open_case's case: a write the gateway registry lets run without approval is called, token-less, in the turn.
    tools = RecordingTools()
    at_once = replace(HOLD, requires_approval=False)
    req = TurnRequest("t1", "th1", SETTINGS, [at_once], user_turn="Hold wire W-88213")
    _, result = await run(req, ports(tools))
    assert result.status == "completed" and result.interrupt is None
    assert [(tool, token) for tool, _, _, token in tools.calls] == [("place_wire_hold", None)]


async def test_approved_resume_runs_stored_input_once_with_same_key() -> None:
    tools = RecordingTools()
    _, first = await run(TurnRequest("t1", "th1", SETTINGS, [HOLD], user_turn="Hold wire W-88213"), ports(tools))
    assert first.interrupt is not None
    resume = Resume(first.interrupt, "approved", approval_token="tok")
    _, result = await run(TurnRequest("t2", "th1", SETTINGS, [HOLD], resume=resume), ports(tools))
    assert result.status == "completed"
    assert tools.calls == [
        ("place_wire_hold", first.interrupt.pending_call.input, first.interrupt.pending_call.key, "tok")
    ]
    assert "hold is in place" in result.text


async def test_rejected_resume_tells_model_and_runs_nothing() -> None:
    tools = RecordingTools()
    _, first = await run(TurnRequest("t1", "th1", SETTINGS, [HOLD], user_turn="Hold wire W-88213"), ports(tools))
    assert first.interrupt is not None
    resume = Resume(first.interrupt, "rejected", reason="Customer confirmed the payee")
    _, result = await run(TurnRequest("t2", "th1", SETTINGS, [HOLD], resume=resume), ports(tools))
    assert tools.calls == []
    assert "rejected" in result.text


async def test_unknown_variable_fails_before_any_model_call() -> None:
    settings = AgentSettings("ag", 1, [PromptFragment("Customer {customer.first_name}", stable=False)], "m")
    _, result = await run(TurnRequest("t1", "th1", settings, [], user_turn="hi"), ports(RecordingTools()))
    assert result.status == "failed"
    assert result.error is not None and "customer.first_name" in result.error


async def test_present_puts_a_shaped_part_on_the_call_without_any_port() -> None:
    """The model returns a comparison as rows; the record carries the part, no tool port is called."""
    tools = RecordingTools()
    rows = [{"product": "Savings Plus", "rate": 3.1}, {"product": "Money Market", "rate": 3.65}]
    ask = f"call present {json.dumps({'shape': 'rows', 'data': rows, 'hint': {'title': 'Compared'}})}"
    req = TurnRequest("t1", "th1", SETTINGS, [], user_turn=ask)
    events, result = await run(req, ports(tools))
    assert tools.calls == [], "present reads nothing and runs through no port"
    (rec,) = result.tool_calls
    assert (rec.tool, rec.server, rec.status) == ("present", "kernel", "ok")
    assert rec.view == {
        "part": {"type": "widget", "id": "", "shape": "rows", "data": rows, "hint": {"title": "Compared"}}
    }
    assert any(isinstance(e, ToolOutput) and e.call.view for e in events)


async def test_present_refuses_a_malformed_part_as_a_tool_error() -> None:
    ask = f"call present {json.dumps({'shape': 'metric', 'data': {'value': 'ten'}})}"
    _, result = await run(TurnRequest("t1", "th1", SETTINGS, [], user_turn=ask), ports(RecordingTools()))
    (rec,) = result.tool_calls
    assert rec.status == "error" and rec.view is None and "label" in str(rec.output)


async def test_an_agent_with_no_tool_calls_can_still_present() -> None:
    """The branch policy agent has max_tool_calls 0: its answer as a widget is not a call to a system, so it is not
    refused by that budget (uc-079's empty reply)."""
    rows = [{"limit": "ATM withdrawal, per day", "amount": "1,000"}]
    ask = f"call present {json.dumps({'shape': 'rows', 'data': rows})}"
    no_calls = AgentSettings("ag_policy", 1, [PromptFragment("You answer from the manual.")], "test-model", 0)
    _, result = await run(TurnRequest("t1", "th1", no_calls, [], user_turn=ask), ports(RecordingTools()))
    assert result.stop_reason == "final", result
    assert [(r.tool, r.status) for r in result.tool_calls] == [("present", "ok")]


async def test_a_turn_stopped_at_the_tool_budget_says_so() -> None:
    """A granted call past the budget stops the turn; the reply says why instead of being empty."""
    tools = RecordingTools()
    ask = 'call place_wire_hold {"wireId": "W-1", "hours": 24, "reason": "x"}'
    no_calls = AgentSettings("ag_fraud", 7, [PromptFragment("You help Fraud Operations.")], "test-model", 0)
    read = ToolGrant("place_wire_hold", "Payments Hub", "Hold a wire", "read", HOLD.input_schema)
    _, result = await run(TurnRequest("t1", "th1", no_calls, [read], user_turn=ask), ports(tools))
    assert result.stop_reason == "max_tool_calls" and tools.calls == [], result
    assert "most tool calls" in result.text


async def test_a_turn_stopped_at_the_step_limit_says_so_not_the_tool_budget() -> None:
    """The step limit raises the library's UsageLimitExceeded too; it was reported as "most tool calls"."""
    steps = AgentSettings("ag_policy", 1, [PromptFragment("You answer from the manual.")], "test-model", 0, 3)
    req = TurnRequest("t1", "th1", steps, [], user_turn="What is the daily ATM withdrawal limit?")
    _, result = await run(req, KernelPorts(model=looping_model(), tools=RecordingTools(), knowledge=FixedKnowledge([])))
    assert result.status == "completed" and result.stop_reason == "max_steps", result
    assert "step limit" in result.text and "most tool calls" not in result.text


async def test_a_reply_cut_short_after_some_text_says_so() -> None:
    steps = AgentSettings("ag_policy", 1, [PromptFragment("You answer from the manual.")], "test-model", 0, 3)
    req = TurnRequest("t1", "th1", steps, [], user_turn="What is the daily ATM withdrawal limit?")
    model = looping_model(text="The daily ATM limit is 1,000. ")
    events, result = await run(req, KernelPorts(model=model, tools=RecordingTools(), knowledge=FixedKnowledge([])))
    assert result.text.startswith("The daily ATM limit is 1,000.")
    assert result.text.endswith("(Reply cut short: the agent reached its step limit for one reply.)"), result.text
    assert isinstance(events[-2], TextDelta) or any(isinstance(e, TextDelta) and "cut short" in e.delta for e in events)


def repeating_model(tool: str, args: dict[str, Any]) -> FunctionModel:
    """A model that calls `tool` with the same `args` for as long as it is offered, then answers from what it has: the
    staging summary turn that called "Get human task" five times and never wrote the summary."""

    def offered(info: AgentInfo) -> bool:
        return any(t.name == tool for t in info.function_tools)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if offered(info):
            return ModelResponse(parts=[ToolCallPart(tool, args)])
        return ModelResponse(parts=[TextPart(ANSWERED)])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if offered(info):
            yield {1: DeltaToolCall(name=tool, json_args=json.dumps(args))}
        else:
            yield ANSWERED

    return FunctionModel(respond, stream_function=stream)


ANSWERED = "Two tasks wait for you this week."
TASK = ToolGrant("get_human_task", "Ops AI", "Get a human task", "read", {"type": "object", "properties": {}})


async def test_an_identical_call_runs_once_and_the_reply_answers_from_it() -> None:
    tools = RecordingTools()
    settings = replace(SETTINGS, max_tool_calls=5)
    req = TurnRequest("t1", "th1", settings, [TASK], user_turn="Give me a summary of what is waiting for me")
    model = repeating_model("get_human_task", {"taskId": "REV-1"})
    _, result = await run(req, KernelPorts(model=model, tools=tools, knowledge=FixedKnowledge([])))
    assert len(tools.calls) == 1, tools.calls
    assert result.stop_reason == "final" and result.text == ANSWERED, result
    assert all(r.status != "running" for r in result.tool_calls), result.tool_calls


async def test_every_open_tool_card_closes_when_the_tool_budget_ends_the_turn() -> None:
    tools = RecordingTools()
    settings = replace(SETTINGS, max_tool_calls=0)
    req = TurnRequest("t1", "th1", settings, [TASK], user_turn="Give me a summary of what is waiting for me")
    model = repeating_model("get_human_task", {"taskId": "REV-1"})
    events, result = await run(req, KernelPorts(model=model, tools=tools, knowledge=FixedKnowledge([])))
    assert result.stop_reason == "max_tool_calls", result
    assert result.tool_calls and all(r.status == "error" for r in result.tool_calls), result.tool_calls
    closed = {e.call.tool_call_id for e in events if isinstance(e, ToolOutput)}
    assert closed == {r.tool_call_id for r in result.tool_calls}, closed


class ReviewFirst(RecordingTools):
    """The gateway's check before sending: a write without an approval waits for a person, with the reason."""

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        self.calls.append((tool, arguments, key, approval_token))
        if approval_token is None:
            return ToolOutcome(False, "needs a person", needs_review="It promises a refund, which the policy forbids.")
        return ToolOutcome(True, {"status": "completed", "reference": "NB-1"})


async def test_a_write_the_gateway_sends_for_review_pauses_with_the_reason_and_runs_once_approved() -> None:
    tools = ReviewFirst()
    at_once = replace(HOLD, requires_approval=False)
    _, first = await run(TurnRequest("t1", "th1", SETTINGS, [at_once], user_turn="Hold wire W-88213"), ports(tools))
    assert first.status == "interrupted" and first.interrupt is not None, first
    assert first.interrupt.needed.endswith("It promises a refund, which the policy forbids."), first.interrupt.needed
    resume = Resume(first.interrupt, "approved", approval_token="tok")
    _, result = await run(TurnRequest("t2", "th1", SETTINGS, [at_once], resume=resume), ports(tools))
    assert result.status == "completed", result
    assert [token for *_, token in tools.calls] == [None, "tok"]


async def test_the_same_call_twice_in_one_step_reaches_the_system_once() -> None:
    # A live turn read one case twice: the library runs a step's calls together, so the repeat was not seen as one.
    class SlowTools(RecordingTools):
        """Answers after a moment, as a real system does, so the step's two calls overlap."""

        async def execute(
            self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
        ) -> ToolOutcome:
            await asyncio.sleep(0.01)
            return await super().execute(tool, arguments, key=key, approval_token=approval_token)

    tools = SlowTools()

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if any(t.name == "get_human_task" for t in info.function_tools) and len(messages) == 1:
            return ModelResponse(
                parts=[ToolCallPart("get_human_task", {"taskId": "REV-1"}, tool_call_id=f"c{i}") for i in (1, 2)]
            )
        return ModelResponse(parts=[TextPart(ANSWERED)])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if any(t.name == "get_human_task" for t in info.function_tools) and len(messages) == 1:
            yield {
                i: DeltaToolCall(name="get_human_task", json_args='{"taskId": "REV-1"}', tool_call_id=f"c{i}")
                for i in (1, 2)
            }
        else:
            yield ANSWERED

    req = TurnRequest("t1", "th1", replace(SETTINGS, max_tool_calls=5), [TASK], user_turn="What is REV-1?")
    _, result = await run(
        req,
        KernelPorts(model=FunctionModel(respond, stream_function=stream), tools=tools, knowledge=FixedKnowledge([])),
    )
    assert len(tools.calls) == 1, tools.calls
    first, second = result.tool_calls
    assert second.output == {"repeatOf": first.tool_call_id}, result.tool_calls


def reading_model(reads: int) -> FunctionModel:
    """A model that makes `reads` reads in one step, then answers from the results it got."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("get_human_task", {"taskId": f"REV-{i}"}) for i in range(reads)])
        return ModelResponse(parts=[TextPart(ANSWERED)])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        part = respond(messages, info).parts
        if isinstance(part[0], TextPart):
            yield part[0].content
        else:
            yield {
                i: DeltaToolCall(name="get_human_task", json_args=json.dumps({"taskId": f"REV-{i}"}))
                for i in range(len(part))
            }

    return FunctionModel(respond, stream_function=stream)


async def test_reads_past_the_tool_budget_are_told_to_stop_and_the_reply_answers_from_the_rest() -> None:
    # A prep turn made six reads in one step under a cap of four and ended with "I reached the most tool calls",
    # throwing away the four reads that had succeeded.
    tools = RecordingTools()
    req = TurnRequest(
        "t1", "th1", replace(SETTINGS, max_tool_calls=2), [TASK], user_turn="Give me a summary of what waits"
    )
    _, result = await run(req, KernelPorts(model=reading_model(3), tools=tools, knowledge=FixedKnowledge([])))
    assert len(tools.calls) == 2, tools.calls
    assert result.stop_reason == "final" and result.text == ANSWERED, result
    assert sorted(r.status for r in result.tool_calls) == ["error", "ok", "ok"], result.tool_calls


SEARCH = ToolGrant(
    "search_knowledge",
    "Knowledge bases",
    "Search knowledge bases",
    "read",
    {"type": "object", "properties": {"query": {"type": "string"}, "collections": {"type": "array"}}},
)


def searching_model(collections: list[str]) -> FunctionModel:
    """A model that searches knowledge once, naming `collections`, then answers."""
    args = {"query": "wire limits", "collections": collections}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("search_knowledge", args, tool_call_id="s1")])
        return ModelResponse(parts=[TextPart(ANSWERED)])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if len(messages) == 1:
            yield {0: DeltaToolCall(name="search_knowledge", json_args=json.dumps(args), tool_call_id="s1")}
        else:
            yield ANSWERED

    return FunctionModel(respond, stream_function=stream)


async def searched(collections: list[str], kb_ids: list[str], *, all_team: bool = False) -> RecordingTools:
    tools = RecordingTools()
    req = TurnRequest(
        "t1", "th1", SETTINGS, [SEARCH], user_turn="What is my wire limit?", kb_ids=kb_ids, all_team_knowledge=all_team
    )
    model = searching_model(collections)
    await run(req, KernelPorts(model=model, tools=tools, knowledge=FixedKnowledge([])))
    return tools


async def test_an_agent_searches_only_its_own_knowledge_bases_unless_it_may_search_the_teams() -> None:
    """The tool searches every base of the team when no collection is named, so a model naming another base, or
    none, would read knowledge the agent was never given."""
    other = await searched(["kb_hr_private"], ["kb_people"])
    assert [a["collections"] for _, a, _, _ in other.calls] == [["kb_people"]]
    none_named = await searched([], ["kb_people", "kb_wires"])
    assert [a["collections"] for _, a, _, _ in none_named.calls] == [["kb_people", "kb_wires"]]
    one_of_its_own = await searched(["kb_wires"], ["kb_people", "kb_wires"])
    assert [a["collections"] for _, a, _, _ in one_of_its_own.calls] == [["kb_wires"]]
    no_bases = await searched([], [])
    assert no_bases.calls == [], "an agent with no bases never reaches the tool"
    team = await searched([], [], all_team=True)
    assert [a.get("allTeamKnowledgeBases") for _, a, _, _ in team.calls] == [True]
