"""A failed tool call reaches the model in words, with its code kept on the call record.

One test per way it breaks: a code reaches the model (F4, every known code and an unknown one, through the kernel's
real tool path); the call log loses the code; the Connect card's own line is replaced; an invalid input loses the
field the model must fix."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agent_kernel.answer_check import error_code
from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.types import AgentSettings, Passage, PromptFragment, ToolGrant, TurnRequest
from ops_agents.api.error_words import WORDS, WordedTools

QUERY = ToolGrant("salesforce_query", "Salesforce", "Query", "read", {"type": "object", "properties": {}})


def refusal(code: str, message: str | None = None, **details: Any) -> dict[str, Any]:
    """The gateway's envelope for a refused call, as tools-service sends it and gateway_error() keeps it."""
    body = {"code": code, "message": message or f"{code}: the call was refused", "status": 409}
    return {"error": body | ({"details": details} if details else {})}


class Failing:
    def __init__(self, outcome: ToolOutcome) -> None:
        self.outcome = outcome

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        return self.outcome


async def said(code: str, **details: Any) -> ToolOutcome:
    port = WordedTools(Failing(ToolOutcome(False, refusal(code, **details))))
    return await port.execute("salesforce_query", {}, key="k", approval_token=None)


@pytest.mark.parametrize("code", [*WORDS, "SOMETHING_NEW"])
async def test_no_code_reaches_the_model(code: str) -> None:
    # F4: the model read {"error": {"code": "CONNECTION_NOT_LINKED", ...}} and repeated it to the person.
    outcome = await said(code)
    seen = json.dumps(outcome.for_model)
    assert error_code(seen) is None, seen
    assert outcome.for_model["what"] and outcome.for_model["next"]


async def test_the_call_log_keeps_the_code() -> None:
    outcome = await said("RATE_LIMITED", app="Salesforce")
    assert outcome.output["error"]["code"] == "RATE_LIMITED"
    assert outcome.for_model["what"] == "Salesforce is busy and asked for fewer calls"
    assert outcome.for_model["retryable"] is True


async def test_the_connect_cards_own_line_is_kept() -> None:
    line = "Not run: the person has not connected their own Salesforce account."
    port = WordedTools(Failing(ToolOutcome(False, refusal("CONNECTION_NOT_LINKED"), for_model=line)))
    outcome = await port.execute("salesforce_query", {}, key="k", approval_token=None)
    assert outcome.for_model == line


async def test_an_invalid_input_keeps_the_field_to_fix() -> None:
    port = WordedTools(Failing(ToolOutcome(False, refusal("INVALID_INPUT", "account_id must be 18 characters"))))
    outcome = await port.execute("salesforce_query", {}, key="k", approval_token=None)
    assert outcome.for_model["detail"] == "account_id must be 18 characters"


async def test_a_failure_already_in_plain_words_reaches_the_model_as_it_is() -> None:
    # "The team has no file named x" became "The call to Files failed", which tells the model less.
    plain = {"error": "The team has no file named q3-forecast.xlsx."}
    port = WordedTools(Failing(ToolOutcome(False, plain)))
    outcome = await port.execute("read_file", {}, key="k", approval_token=None)
    assert outcome.for_model is None and outcome.output == plain


class NoKnowledge:
    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Passage]:
        return []


async def test_through_the_kernel_the_model_reads_words_and_the_record_keeps_the_code() -> None:
    seen: list[Any] = []

    def reply(messages: list[ModelMessage]) -> ModelResponse:
        back = [p for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart)]
        if back:
            seen.append(back[-1].content)
            return ModelResponse(parts=[TextPart("Salesforce needs your sign-in.")])
        return ModelResponse(parts=[ToolCallPart("salesforce_query", {})])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        part = reply(messages).parts[0]
        if isinstance(part, TextPart):
            yield part.content
        else:
            yield {0: DeltaToolCall(name="salesforce_query", json_args="{}")}

    model = FunctionModel(lambda m, _i: reply(m), stream_function=stream)
    port = WordedTools(Failing(ToolOutcome(False, refusal("NOT_SIGNED_IN", app="Salesforce"))))
    settings = AgentSettings("ag", 1, [PromptFragment("You are Ops Assistant.")], "m")
    req = TurnRequest("t1", "th1", settings, [QUERY], user_turn="List accounts")
    events = [e async for e in run_turn(req, KernelPorts(model=model, tools=port, knowledge=NoKnowledge()))]
    result = events[-1]
    assert isinstance(result, TurnFinished)
    assert error_code(json.dumps(seen[0])) is None, seen[0]
    assert seen[0]["error"]["what"] == "Salesforce needs you to sign in again"
    assert result.result.tool_calls[0].output["error"]["code"] == "NOT_SIGNED_IN"
