"""Workflow AI steps (c-298) on the engine with a fake prompt port, by failure mode: a confident answer leaves by the
wrong port, or a doubtful one by a category instead of otherwise; a wire to a category the step no longer has is
saved; an answer outside the schema is retried and paid for again; Extract from text asks for fields other than the
document type's; a step's settings never reach the model."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from ops_engine import default_registry
from ops_engine.compiler import channel, compile_definition
from ops_engine.definition import parse, validate
from ops_engine.journal import MemoryJournal
from ops_engine.ports import AgentResult, EnginePorts, PromptRequest

from .test_compiler import FakeReviews, FakeTools, config

CATEGORIES = [
    {"name": "fraud", "description": "The customer reports a payment they did not make"},
    {"name": "billing", "description": "A question about fees or a statement"},
]
LEVY_FIELDS = [{"key": "amount", "label": "Amount", "type": "money"}, {"key": "case_no", "label": "Case number"}]


class Prompts:
    """Answers each call with the next scripted answer (None: an answer outside the schema) and keeps the requests."""

    def __init__(self, *answers: dict[str, Any] | None) -> None:
        self.answers = list(answers)
        self.requests: list[PromptRequest] = []

    async def prompt(self, request: PromptRequest) -> AgentResult:
        self.requests.append(request)
        answer = self.answers.pop(0)
        return AgentResult(True, answer) if answer is not None else AgentResult(False, code="schema_error", error="no")


class DocumentTypes:
    def __init__(self) -> None:
        self.asked: list[tuple[str, int | None]] = []

    async def fields(self, run_id: str, type_id: str, version: int | None) -> list[dict[str, Any]]:
        self.asked.append((type_id, version))
        return LEVY_FIELDS


def flow(step: dict[str, Any], ports: list[str]) -> Any:
    ends = [{"id": f"end_{p}", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": p}} for p in ports]
    return parse(
        {
            "schemaVersion": 2,
            "id": "ai_steps",
            "nodes": [{"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}}, step, *ends],
            "connections": [
                {"from": {"node": "in", "port": "payload"}, "to": {"node": "ai", "port": "in"}},
                *[{"from": {"node": "ai", "port": p}, "to": {"node": f"end_{p}", "port": "in"}} for p in ports],
            ],
        }
    )


def classify(floor: float = 0.6) -> dict[str, Any]:
    params = {"text": "$.input.body", "categories": CATEGORIES, "minConfidence": floor, "model": "bank-reasoning"}
    return {"id": "ai", "type": "ops.ai.classify", "typeVersion": 1, "parameters": params}


async def run(d: Any, ports: EnginePorts, thread: str, body: Any = "I never paid Acme 900 dollars") -> dict[str, Any]:
    assert validate(d, default_registry()) == [], validate(d, default_registry())
    g = compile_definition(d, default_registry(), ports=ports, journal=MemoryJournal(), checkpointer=InMemorySaver())
    await g.ainvoke({"input": {"body": body}}, config(thread), durability="sync")
    return (await g.aget_state(config(thread))).values[channel("ai")]


def ports(prompts: Prompts, types: DocumentTypes | None = None) -> EnginePorts:
    return EnginePorts(tools=FakeTools(), reviews=FakeReviews(), prompts=prompts, document_types=types)


@pytest.mark.parametrize(
    ("answer", "port"),
    [
        ({"category": "fraud", "confidence": 0.92, "reason": "Unrecognised payment"}, "fraud"),
        ({"category": "billing", "confidence": 0.41, "reason": "Maybe a fee"}, "otherwise"),
        ({"category": "none", "confidence": 0.9, "reason": "Neither"}, "otherwise"),
    ],
)
async def test_classify_leaves_by_the_category_or_by_otherwise_when_unsure(answer: dict[str, Any], port: str) -> None:
    prompts = Prompts(answer)
    step = await run(
        flow(classify(), ["fraud", "billing", "otherwise", "error"]), ports(prompts), f"c-{port}-{answer['category']}"
    )
    assert step["port"] == port and step["out"]["confidence"] == answer["confidence"], step
    [req] = prompts.requests
    # The step's settings reach the model: its categories in the schema and the instructions, its alias, its text.
    assert req.output_schema["properties"]["category"]["enum"] == ["fraud", "billing", "none"]
    assert "fraud: The customer reports a payment" in req.instructions
    assert (req.model_alias, req.message) == ("bank-reasoning", "I never paid Acme 900 dollars")


def test_a_wire_to_a_category_the_step_no_longer_has_is_refused() -> None:
    d = flow(classify(), ["fraud", "billing", "otherwise", "chargeback"])
    assert any(c["node"] == "ai" for c in validate(d, default_registry())), "a wire from a removed category is refused"


async def test_an_answer_outside_the_schema_takes_the_error_port_after_one_call() -> None:
    prompts = Prompts(None)
    step_def = {"id": "ai", "type": "ops.ai.summarise", "typeVersion": 1, "parameters": {"text": "$.input.body"}}
    step = await run(flow(step_def, ["ok", "error"]), ports(prompts), "s-1")
    assert (step["port"], step["out"]["code"]) == ("error", "schema_error") and len(prompts.requests) == 1


async def test_extract_from_text_asks_for_the_document_types_fields() -> None:
    prompts, types = Prompts({"amount": 3250.0, "case_no": None}), DocumentTypes()
    params = {"text": "$.input.body", "documentType": {"id": "levy_notice", "version": 3}}
    step_def = {"id": "ai", "type": "ops.ai.extractText", "typeVersion": 1, "parameters": params}
    step = await run(flow(step_def, ["ok", "error"]), ports(prompts, types), "e-1", "Levy of 3,250.00")
    assert types.asked == [("levy_notice", 3)]
    schema = prompts.requests[0].output_schema
    assert (schema["required"], schema["properties"]["amount"]["type"]) == (["amount", "case_no"], ["number", "null"])
    assert step["out"] == {"amount": 3250.0, "case_no": None}


async def test_a_draft_returns_its_text_and_reads_the_steps_instructions() -> None:
    prompts = Prompts({"subject": "Your dispute", "body": "We have opened a dispute for the 900 dollar payment."})
    params = {"text": "$.input.body", "instructions": "Reply to the customer; say a dispute is open."}
    step_def = {"id": "ai", "type": "ops.ai.draft", "typeVersion": 1, "parameters": params}
    step = await run(flow(step_def, ["ok", "error"]), ports(prompts), "d-1")
    assert step["port"] == "ok" and step["out"]["body"].startswith("We have opened a dispute"), step
    assert "say a dispute is open" in prompts.requests[0].instructions
