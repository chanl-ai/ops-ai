"""An agent with many tools finds them by searching (c-610), by failure mode: every schema still sent above the
threshold, a found tool that cannot be called, an approved write that cannot resume because its tool is hidden again,
a search or a guessed name reaching a tool the agent is not granted, an agent at the threshold or with the install flag
off changing behaviour, and the agents-service catalog dropping the deployment's setting."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agent_kernel.events import KernelEvent, TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.types import (
    TOOL_SEARCH_ABOVE,
    AgentSettings,
    PromptFragment,
    Resume,
    ToolGrant,
    TurnRequest,
    TurnResult,
)
from ops_agents.activities.catalog import load_catalog
from tests.conftest import SEED as SEED_DIR

SCHEMA: dict[str, Any] = {"type": "object", "properties": {"customerId": {"type": "string"}}}
# 40 tools from systems a bank, an insurer and a retailer connect, plus the one each test needs.
FILLER = [
    ToolGrant(f"{system}_{verb}_{n}", system, f"{verb.title()} a {system} record number {n}.", "read", SCHEMA)
    for n in range(10)
    for system, verb in (("crm", "list"), ("claims", "export"), ("orders", "archive"), ("ledger", "sync"))
]
BALANCE = ToolGrant("get_account_balance", "bank", "Read a customer's account balance.", "read", SCHEMA)
HOLD = ToolGrant("place_hold", "bank", "Place a hold on a customer's account.", "write", SCHEMA)
# The install flag tool_search on, at its default threshold.
SETTINGS = AgentSettings(
    "ag_ops", 1, [PromptFragment("You help bank operations.")], "m", tool_search_above=TOOL_SEARCH_ABOVE
)


class Tools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        self.calls.append((tool, approval_token))
        return ToolOutcome(True, {"tool": tool, "status": "done"})


class NoKnowledge:
    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Any]:
        return []


Step = Callable[[list[ModelMessage]], ModelResponse]


class Model:
    """Answers each request with the next step and keeps the function tools each request offered."""

    def __init__(self, steps: list[Step]) -> None:
        self.steps = steps
        self.offered: list[list[str]] = []

    def respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.offered.append(sorted(t.name for t in info.function_tools))
        return self.steps[min(len(self.offered), len(self.steps)) - 1](messages)

    def build(self) -> FunctionModel:
        async def stream(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
            for i, part in enumerate(self.respond(messages, info).parts):
                if isinstance(part, TextPart):
                    yield part.content
                elif isinstance(part, ToolCallPart):
                    yield {i: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args))}

        return FunctionModel(self.respond, stream_function=stream)


def call(tool: str, args: dict[str, Any]) -> Step:
    return lambda _m: ModelResponse(parts=[ToolCallPart(tool, args)])


def say(text: str) -> Step:
    return lambda _m: ModelResponse(parts=[TextPart(text)])


def found(messages: list[ModelMessage]) -> list[str]:
    """What the last search returned to the model."""
    for m in reversed(messages):
        for p in getattr(m, "parts", []):
            if isinstance(p, ToolReturnPart) and p.tool_name == "search_tools":
                return [x["name"] for x in json.loads(json.dumps(p.model_response_object())).get("discovered", [])]
    return []


async def turn(model: Model, tools: Tools, grants: list[ToolGrant], **kw: Any) -> TurnResult:
    req = TurnRequest("t1", "r1", kw.pop("settings", SETTINGS), grants, **kw)
    ports = KernelPorts(model=model.build(), tools=tools, knowledge=NoKnowledge())
    events: list[KernelEvent] = [e async for e in run_turn(req, ports)]
    last = events[-1]
    assert isinstance(last, TurnFinished)
    return last.result


async def test_only_builtins_offered_until_a_search() -> None:
    model = Model([say("I need to look first.")])
    await turn(model, Tools(), [*FILLER, BALANCE], user_turn="What is Priya's balance?")
    assert model.offered[0] == ["present", "search_tools"], model.offered[0]


async def test_a_search_reveals_its_matches_for_the_next_step() -> None:
    tools = Tools()
    model = Model(
        [
            call("search_tools", {"queries": ["account balance"]}),
            call("get_account_balance", {"customerId": "CUS-1002"}),
            say("Priya's balance is ready."),
        ]
    )
    result = await turn(model, tools, [*FILLER, BALANCE], user_turn="What is Priya's balance?")
    assert result.status == "completed", result.error
    assert "get_account_balance" in model.offered[1] and len(model.offered[1]) < 10, model.offered[1]
    assert tools.calls == [("get_account_balance", None)]
    searched = next(c for c in result.tool_calls if c.tool == "search_tools")
    assert searched.status == "ok" and "get_account_balance" in json.dumps(searched.output, default=str)


async def test_a_found_gated_write_pauses_and_resumes() -> None:
    tools = Tools()
    steps = [
        call("search_tools", {"queries": ["hold account"]}),
        call("place_hold", {"customerId": "CUS-1002"}),
        say("The hold is in place."),
    ]
    first = await turn(Model(steps), tools, [*FILLER, HOLD], user_turn="Hold Priya's account.")
    assert first.status == "interrupted" and first.interrupt is not None and tools.calls == []
    resume = Resume(first.interrupt, "approved", approval_token="tok")
    model = Model([say("The hold is in place.")])
    result = await turn(model, tools, [*FILLER, HOLD], resume=resume)
    assert result.status == "completed", result.error
    assert tools.calls == [("place_hold", "tok")], "the approved write runs once, with its token"


async def test_an_ungranted_name_is_refused() -> None:
    tools = Tools()
    model = Model(
        [
            call("search_tools", {"queries": ["wire transfer"]}),
            call("send_wire", {"customerId": "CUS-1002"}),
            say("I cannot send wires."),
        ]
    )
    result = await turn(model, tools, [*FILLER, BALANCE], user_turn="Send a wire for Priya.")
    assert result.status == "completed", result.error
    assert tools.calls == [], "nothing reached the gateway"
    guessed = next(c for c in result.tool_calls if c.tool == "send_wire")
    assert guessed.status == "error" and guessed.server == "none"


async def test_at_the_threshold_everything_is_offered() -> None:
    model = Model([say("Here.")])
    grants = [*FILLER[:19], BALANCE]
    await turn(model, Tools(), grants, user_turn="What is Priya's balance?")
    assert set(model.offered[0]) >= {"get_account_balance", "search_tools", *(g.name for g in FILLER[:19])}
    low = replace(SETTINGS, tool_search_above=0)
    lowered = Model([say("Here.")])
    await turn(lowered, Tools(), [BALANCE], user_turn="Balance?", settings=low)
    assert lowered.offered[0] == ["present", "search_tools"], "0 searches for every agent"


def test_the_catalog_carries_the_deployment_setting() -> None:
    agent = load_catalog(SEED_DIR).agents[0]
    catalogs = [
        load_catalog(SEED_DIR),
        load_catalog(SEED_DIR, tool_search=True),
        load_catalog(SEED_DIR, tool_search=True, tool_search_above=3),
    ]
    above = [c.settings_for(agent, "default").tool_search_above for c in catalogs]
    assert above == [None, 20, 3], "off by default; on, the kernel's 20 or the deployment's number"


async def test_with_the_flag_off_every_tool_is_offered() -> None:
    model = Model([say("Here.")])
    off = replace(SETTINGS, tool_search_above=None)
    await turn(model, Tools(), [*FILLER, BALANCE], user_turn="What is Priya's balance?", settings=off)
    assert "get_account_balance" in model.offered[0] and len(model.offered[0]) == len(FILLER) + 3
