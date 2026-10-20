"""A turn given an output schema (c-062 T001), by failure mode: the answer returned as free text where a workflow step
needs structured output, output that does not match the schema passed on as if it did, and a schema that never
reaches the model call (so a real model is never asked for it). Through a scripted model and the fake OpenAI."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx2
from openai import AsyncOpenAI
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.types import AgentSettings, PromptFragment, TurnRequest, TurnResult
from tests.unit.test_extract_records import fake_openai

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"category": {"type": "string", "enum": ["dispute", "fraud"]}, "amount": {"type": "number"}},
    "required": ["category", "amount"],
}
SETTINGS = AgentSettings("ag_triage", 1, [PromptFragment("You triage emails.")], "test-model")


class NoTools:
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        raise AssertionError("no tool runs in these turns")


class NoKnowledge:
    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Any]:
        return []


async def turn(model: Any, schema: dict[str, Any] | None = SCHEMA) -> TurnResult:
    req = TurnRequest("t1", "r1", SETTINGS, [], user_turn="Card charged twice for 42.50", output_schema=schema)
    events = [e async for e in run_turn(req, KernelPorts(model=model, tools=NoTools(), knowledge=NoKnowledge()))]
    return events[-1].result  # type: ignore[attr-defined]


def answering(*responses: ModelResponse) -> FunctionModel:
    """A model that returns `responses` in order, and records the output tools it was offered."""
    queue = list(responses)
    offered: list[str] = []

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        p = info.model_request_parameters
        offered.extend([p.output_mode, *(t.name for t in info.output_tools)])
        if p.output_object is not None and p.output_object.name:
            offered.append(p.output_object.name)
        return queue.pop(0) if len(queue) > 1 else queue[0]

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        response = reply(messages, info)
        for i, part in enumerate(response.parts):
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                yield {i: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args))}

    model = FunctionModel(reply, stream_function=stream)
    model.offered = offered  # type: ignore[attr-defined]
    return model


async def test_output_matching_the_schema_is_returned_validated() -> None:
    model = answering(ModelResponse(parts=[TextPart(json.dumps({"category": "dispute", "amount": 42.5}))]))
    result = await turn(model)
    assert (result.status, result.stop_reason, result.output) == (
        "completed",
        "final",
        {"category": "dispute", "amount": 42.5},
    )
    # The schema reaches the model call as its native response format, not an output tool it could skip.
    assert {"native", "final_result"} <= set(model.offered), model.offered  # type: ignore[attr-defined]


async def test_output_not_matching_the_schema_is_a_schema_error() -> None:
    bad = ModelResponse(parts=[TextPart(json.dumps({"category": "spam", "amount": "lots"}))])
    result = await turn(answering(bad))
    assert (result.status, result.stop_reason, result.error_code, result.output) == (
        "failed",
        "schema_error",
        "schema_error",
        None,
    ), result
    assert result.error and "amount" in result.error, "the validation message names what failed"


async def test_free_text_where_a_schema_is_required_is_a_schema_error() -> None:
    result = await turn(answering(ModelResponse(parts=[TextPart("It looks like a dispute.")])))
    assert (result.status, result.error_code, result.output) == ("failed", "schema_error", None), result


async def test_a_turn_without_a_schema_still_answers_in_text() -> None:
    result = await turn(answering(ModelResponse(parts=[TextPart("A dispute.")])), schema=None)
    assert (result.stop_reason, result.text, result.output) == ("final", "A dispute.", None)


async def test_the_fake_openai_scripts_a_structured_answer(tmp_path: Path) -> None:
    rule = {
        "when": "charged twice for (?P<amount>[\\d.]+)",
        "tool": "final_result",
        "arguments": {"category": "dispute", "amount": 42.5},
    }
    (tmp_path / "script.json").write_text(json.dumps({"models": ["default"], "rules": [rule]}))
    fake = fake_openai()
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=fake.create_app(fake.load_script(tmp_path))))
    client = AsyncOpenAI(base_url="http://fake/v1", api_key="fake", max_retries=0, http_client=http)
    result = await turn(OpenAIChatModel("default", provider=OpenAIProvider(openai_client=client)))
    assert (result.stop_reason, result.output) == ("final", {"category": "dispute", "amount": 42.5}), result


async def test_a_turn_that_ends_without_output_under_a_schema_is_no_output() -> None:
    # The customer_summary run on shared, 2026-10-18: the turn ended before the model was asked (knowledge out of
    # reach), "completed" with no output, and the workflow step took its ok port with null. A refusal, withdrawn or
    # unreachable knowledge and a step limit all end this way; each is a failure the step's error port takes.
    req = TurnRequest(
        "t1", "r1", SETTINGS, [], user_turn="Summarise Priya Natarajan", output_schema=SCHEMA, knowledge_withdrawn=True
    )
    model = answering(ModelResponse(parts=[ToolCallPart("final_result", {"category": "dispute", "amount": 1.0})]))
    events = [e async for e in run_turn(req, KernelPorts(model=model, tools=NoTools(), knowledge=NoKnowledge()))]
    finished = events[-1]
    assert isinstance(finished, TurnFinished), finished
    result = finished.result
    assert (result.status, result.stop_reason, result.error_code, result.output) == (
        "failed",
        "no_output",
        "no_output",
        None,
    ), result
    assert result.error and result.error == result.text, "the reason the turn gave is the step's error"
