"""A chat reusing what it already read, by failure mode: a follow-up that reads the same record again, a stale read
after a save, another person or chat given someone's read, a read kept past its expiry, the model told the raw result
in place of the masked one it saw first, and a reused read the call log shows as a fresh one."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.tool_cache import EARLIER, ToolCache
from ops_agent_kernel.types import AgentSettings, PromptFragment, ToolGrant, TurnRequest, TurnResult
from ops_agents.activities.catalog import load_catalog
from ops_agents.api.chat_threads import AssistantBuilder
from ops_agents.api.read_caches import ChatReads
from ops_agents.api.run_person import RUN_PERSON, RunPerson
from ops_contracts.chat import ChatMessage
from tests.conftest import SEED

SETTINGS = replace(
    AgentSettings("ag_ops", 1, [PromptFragment("You help the sales team.")], "test-model"), max_tool_calls=5
)
ACCOUNT = {"accountId": "001A"}
READ = ToolGrant("get_account", "salesforce", "Read an account", "read", {"type": "object", "properties": {}})
SAVE = replace(
    ToolGrant("save_records", "salesforce", "Save records", "write", {"type": "object", "properties": {}}),
    requires_approval=False,
)


class Tools:
    def __init__(self, for_model: Any = None) -> None:
        self.calls: list[str] = []
        self.for_model = for_model

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        self.calls.append(tool)
        return ToolOutcome(True, {"name": "Acme Corp", "phone": "555-0100"}, for_model=self.for_model)


class OneChat:
    """The cache of one chat and person, as ChatReads gives it for every call of that chat."""

    def __init__(self, cache: ToolCache | None = None) -> None:
        self.cache = cache or ToolCache()

    async def current(self) -> ToolCache | None:
        return self.cache


def calling(*calls: tuple[str, dict[str, Any]], told: list[Any] | None = None) -> FunctionModel:
    """A model that makes `calls` one per step, then answers; what each call returned is added to `told`."""

    def step(messages: list[ModelMessage]) -> int:
        return sum(isinstance(m, ModelResponse) for m in messages)

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        if told is not None and isinstance(last, ModelRequest):
            told.extend(p.content for p in last.parts if isinstance(p, ToolReturnPart))
        n = step(messages)
        if n < len(calls):
            return ModelResponse(parts=[ToolCallPart(calls[n][0], calls[n][1], tool_call_id=f"c{n}")])
        return ModelResponse(parts=[TextPart("Acme's phone is 555-0100.")])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        part = respond(messages, info).parts[0]
        if isinstance(part, ToolCallPart):
            yield {
                1: DeltaToolCall(name=part.tool_name, json_args=part.args_as_json_str(), tool_call_id=part.tool_call_id)
            }
        elif isinstance(part, TextPart):
            yield part.content

    return FunctionModel(respond, stream_function=stream)


async def turn(model: FunctionModel, tools: Tools, chat: OneChat, ask: str = "What is Acme's phone?") -> TurnResult:
    req = TurnRequest("t", "r", SETTINGS, [READ, SAVE], user_turn=ask)
    ports = KernelPorts(model=model, tools=tools, knowledge=Empty(), tool_caches=chat)
    events = [e async for e in run_turn(req, ports)]
    assert isinstance(events[-1], TurnFinished)
    return events[-1].result


class Empty:
    async def search(self, query: str, kb_ids: list[str]) -> list[Any]:
        return []


async def test_a_follow_up_that_makes_the_same_read_does_not_reach_the_app_and_says_it_is_from_earlier() -> None:
    tools, chat, told = Tools(), OneChat(), list[Any]()
    await turn(calling(("get_account", ACCOUNT)), tools, chat)
    result = await turn(calling(("get_account", ACCOUNT), told=told), tools, chat, "And its owner?")
    assert tools.calls == ["get_account"], tools.calls
    assert told and told[0]["note"] == EARLIER, told
    assert [r.cached for r in result.tool_calls] == [True], result.tool_calls


async def test_a_save_to_the_app_makes_the_next_read_read_again() -> None:
    tools, chat = Tools(), OneChat()
    await turn(calling(("get_account", ACCOUNT)), tools, chat)
    await turn(calling(("save_records", {"records": [{"Id": "001A", "Phone": "555-0199"}]})), tools, chat, "Save it")
    result = await turn(calling(("get_account", ACCOUNT)), tools, chat, "What is the phone now?")
    assert tools.calls == ["get_account", "save_records", "get_account"], tools.calls
    assert [r.cached for r in result.tool_calls] == [False]


async def test_a_reused_read_tells_the_model_what_it_was_told_first_not_the_raw_result() -> None:
    masked = {"name": "Acme Corp", "phone": "[phone]"}
    tools, chat, told = Tools(for_model=masked), OneChat(), list[Any]()
    await turn(calling(("get_account", ACCOUNT)), tools, chat)
    await turn(calling(("get_account", ACCOUNT), told=told), tools, chat, "And its owner?")
    assert told[0]["result"] == masked, told


async def test_a_read_older_than_the_expiry_is_read_again() -> None:
    now = [0.0]
    tools, chat = Tools(), OneChat(ToolCache(keep_s=300, clock=lambda: now[0]))
    await turn(calling(("get_account", ACCOUNT)), tools, chat)
    now[0] = 301
    await turn(calling(("get_account", ACCOUNT)), tools, chat, "And its owner?")
    assert tools.calls == ["get_account", "get_account"], tools.calls


async def test_another_person_or_another_chat_never_gets_a_read_and_a_run_with_no_chat_person_keeps_none() -> None:
    reads = ChatReads()

    async def cache_of(person: RunPerson | None) -> ToolCache | None:
        token = RUN_PERSON.set(person)
        try:
            return await reads.current()
        finally:
            RUN_PERSON.reset(token)

    james = await cache_of(RunPerson("james@example.com", "th_1"))
    assert james is not None
    james.put("salesforce", "get_account", "h", {"name": "Acme Corp"})
    assert (await cache_of(RunPerson("james@example.com", "th_1"))) is james
    farah = await cache_of(RunPerson("farah@example.com", "th_1"))
    other_chat = await cache_of(RunPerson("james@example.com", "th_2"))
    assert farah is not None and farah.get("salesforce", "get_account", "h") is None
    assert other_chat is not None and other_chat.get("salesforce", "get_account", "h") is None
    assert await cache_of(None) is None, "a workflow run reads every time"
    assert await cache_of(RunPerson(None, "th_1")) is None, "a chat whose person is not known keeps nothing"


def test_the_call_log_says_a_reused_read_came_from_earlier_in_the_chat() -> None:
    builder = AssistantBuilder(load_catalog(SEED), ChatMessage(id="m1", role="assistant", content="", at="t"))
    call: dict[str, Any] = {"id": "c1", "tool": "get_account", "server": "salesforce", "input": ACCOUNT, "status": "ok"}
    builder.apply("tool_call", {**call, "output": {"name": "Acme Corp"}, "cached": True})
    builder.apply("tool_call", {**call, "id": "c2", "output": {"name": "Acme Corp"}})
    labels = [c.label or "" for c in builder.message.tool_calls or []]
    assert labels[0].endswith("from earlier in this chat") and not labels[1].endswith("from earlier in this chat")
