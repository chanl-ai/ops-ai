"""A turn given an output schema, by failure mode: the answer returned as free text where a workflow step
needs structured output, output that does not match the schema passed on as if it did, and a schema that never
reaches the model call (so a real model is never asked for it). Through a scripted model and the fake OpenAI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import httpx2
from openai import AsyncOpenAI

from ops_agent_kernel.contract import ModelEndpoint
from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.testing import Answer, Reply, ScriptedModel, ToolCall, tool_names
from ops_agent_kernel.types import AgentSettings, PromptFragment, TurnRequest, TurnResult
from ops_service_kit.http import Json
from tests.conftest import wired
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
    async def search(self, query: str, kb_ids: list[str]) -> list[Any]:
        return []


async def turn(model: Any, schema: dict[str, Any] | None = SCHEMA) -> TurnResult:
    req = TurnRequest("t1", "r1", SETTINGS, [], user_turn="Card charged twice for 42.50", output_schema=schema)
    events = [e async for e in run_turn(req, KernelPorts(model=model, tools=NoTools(), knowledge=NoKnowledge()))]
    return events[-1].result  # type: ignore[attr-defined]


def answering(*responses: Answer) -> tuple[ModelEndpoint, ScriptedModel]:
    """A model that returns `responses` in order, and the transport that keeps each request it was sent."""
    queue = list(responses)

    def script(messages: list[Json], tools: list[Json]) -> Answer:
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return wired(script)


def response_format(wire: ScriptedModel) -> Json:
    return cast(Json, wire.requests[0].get("response_format") or {})


async def test_output_matching_the_schema_is_returned_validated() -> None:
    model, wire = answering(json.dumps({"category": "dispute", "amount": 42.5}))
    result = await turn(model)
    assert (result.status, result.stop_reason, result.output) == (
        "completed",
        "final",
        {"category": "dispute", "amount": 42.5},
    )
    # The schema reaches the model call as its native response format, not an output tool it could skip.
    sent = response_format(wire)
    assert sent.get("type") == "json_schema" and cast(Json, sent["json_schema"])["name"] == "final_result", sent
    offered = tool_names(cast(list[Json], wire.requests[0].get("tools") or []))
    assert "final_result" not in offered, offered


async def test_output_not_matching_the_schema_is_a_schema_error() -> None:
    bad = json.dumps({"category": "spam", "amount": "lots"})
    result = await turn(answering(bad)[0])
    assert (result.status, result.stop_reason, result.error_code, result.output) == (
        "failed",
        "schema_error",
        "schema_error",
        None,
    ), result
    assert result.error and "amount" in result.error, "the validation message names what failed"


async def test_free_text_where_a_schema_is_required_is_a_schema_error() -> None:
    result = await turn(answering("It looks like a dispute.")[0])
    assert (result.status, result.error_code, result.output) == ("failed", "schema_error", None), result


async def test_a_turn_without_a_schema_still_answers_in_text() -> None:
    result = await turn(answering("A dispute.")[0], schema=None)
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
    result = await turn(ModelEndpoint(client, "default"))
    assert (result.stop_reason, result.output) == ("final", {"category": "dispute", "amount": 42.5}), result


async def test_a_turn_that_ends_without_output_under_a_schema_is_no_output() -> None:
    # The customer_summary run on shared, 2026-10-18: the turn ended before the model was asked (knowledge out of
    # reach), "completed" with no output, and the workflow step took its ok port with null. A refusal, withdrawn or
    # unreachable knowledge and a step limit all end this way; each is a failure the step's error port takes.
    req = TurnRequest(
        "t1", "r1", SETTINGS, [], user_turn="Summarise Priya Natarajan", output_schema=SCHEMA, knowledge_withdrawn=True
    )
    model, _ = answering(Reply(tool_calls=[ToolCall("final_result", {"category": "dispute", "amount": 1.0})]))
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
