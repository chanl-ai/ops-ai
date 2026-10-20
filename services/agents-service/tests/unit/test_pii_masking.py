"""Masking personal data in what an agent's turn shows (c-293), by failure mode: an SSN, its last
four, a card or account number, an email or a phone reaches a reply, a stored message, a step's output or a citation;
a number streamed across two chunks shows its first half unmasked; an amount, a date or a case number is masked by
mistake; the model stops seeing the real value, so a turn cannot chain on it; the setting off still masks."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agent_kernel.events import CitationsReady, KernelEvent, TextDelta, TextReplaced, ToolOutput, TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.pii import StreamMasker, mask
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.types import AgentSettings, Passage, PromptFragment, ToolGrant, TurnRequest

READ = ToolGrant(
    "get_customer",
    "Core banking",
    "Read a customer",
    "read",
    {"type": "object", "properties": {"id": {"type": "string"}}},
)
RECORD = {"name": "Ann Lee", "ssn": "123-45-6789", "email": "ann.lee@example.com", "account": "4401235567"}
REPLY = "Ann Lee, SSN ending 6789, email ann.lee@example.com, phone (902) 555-0147, account 4401235567."


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("SSN 123-45-6789", "SSN [SSN]"),
        ("her SSN ending 6789", "her SSN ending ••••"),
        ("social security number 6789", "social security number ••••"),
        ("write to ann.lee@example.com today", "write to [email] today"),
        ("call (902) 555-0147 or +1 902-555-0147", "call [phone] or [phone]"),
        ("card 4111 1111 1111 1111", "card [card]"),
        ("card ending 4410", "card ending ••••"),
        ("account 4401235567", "account ••••"),
        ("ref 4401235567", "ref [account]"),
    ],
)
def test_each_kind_of_personal_data_is_masked(text: str, shown: str) -> None:
    assert mask(text) == shown


@pytest.mark.parametrize(
    "text",
    [
        "a levy of 3,250.00 CAD",
        "served 2026-10-14",
        "case NS-2026-GN-01187",
        "wire W-88213",
        "page 1 of 3, in 2026",
        # Ids carry digit runs glued to letters (uc-233: a run's file id came back as fil_13cf059e[account]...).
        "fil_13cf059e9367473281ca9d7d61f8d116",
        "wfrun_273808292bd7",
        "doc 4f1234567890123456ab",
    ],
)
def test_amounts_dates_case_numbers_and_ids_are_not_masked(text: str) -> None:
    assert mask(text) == text


@pytest.mark.parametrize("cut", range(1, len(REPLY)))
def test_a_number_split_across_chunks_is_never_shown_in_part(cut: int) -> None:
    stream = StreamMasker()
    shown = stream.push(REPLY[:cut]) + stream.push(REPLY[cut:]) + stream.flush()
    assert shown == mask(REPLY)
    assert "6789" not in shown and "ann.lee" not in shown and "4401235567" not in shown and "555-0147" not in shown


class Tools:
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        return ToolOutcome(True, RECORD)


def turn_model(seen: list[str]) -> FunctionModel:
    """Reads the customer, then answers with what it read; `seen` keeps every tool result the model was given."""

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returns = [p for m in messages if isinstance(m, ModelRequest) for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart("get_customer", {"id": "C-1001"})])
        seen.extend(json.dumps(p.content) for p in returns)
        return ModelResponse(parts=[TextPart(REPLY)])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        for part in reply(messages, info).parts:
            if isinstance(part, ToolCallPart):
                yield {0: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args))}
            elif isinstance(part, TextPart):
                # Small chunks, so numbers and the email arrive split.
                for i in range(0, len(part.content), 5):
                    yield part.content[i : i + 5]

    return FunctionModel(reply, stream_function=stream)


async def turn(redact: bool) -> tuple[list[KernelEvent], list[str]]:
    seen: list[str] = []
    settings = replace(AgentSettings("ag_x", 1, [PromptFragment("You help.")], "test-model"), redact_pii=redact)
    req = TurnRequest("t1", "th1", settings, [READ], user_turn="Who is C-1001?")
    events = [e async for e in run_turn(req, KernelPorts(model=turn_model(seen), tools=Tools(), knowledge=None))]  # type: ignore[arg-type]
    return events, seen


async def test_what_a_turn_shows_is_masked_while_the_model_reads_the_real_values() -> None:
    events, seen = await turn(redact=True)
    streamed = "".join(e.delta for e in events if isinstance(e, TextDelta))
    [output] = [e.call.output for e in events if isinstance(e, ToolOutput)]
    finished = events[-1]
    assert isinstance(finished, TurnFinished)
    assert streamed == mask(REPLY) == finished.result.text
    assert output == {"name": "Ann Lee", "ssn": "[SSN]", "email": "[email]", "account": "[account]"}
    assert finished.result.tool_calls[0].output == output
    # The model was given the record as it is, so it can chain on the account id.
    assert any("123-45-6789" in s and "4401235567" in s for s in seen)
    assert not any(isinstance(e, TextReplaced) for e in events)


async def test_with_the_setting_off_nothing_is_masked() -> None:
    events, _ = await turn(redact=False)
    finished = events[-1]
    assert isinstance(finished, TurnFinished) and finished.result.text == REPLY


class Knowledge:
    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Passage]:
        return [
            Passage("doc_1", "Customer notes", "Contact", "1", "Ann Lee, SSN 123-45-6789, ann.lee@example.com.", "kb_1")
        ]


async def test_a_cited_passage_is_masked_where_people_see_it() -> None:
    """tick 30: citations carried the passage text unmasked, in the stream and in the stored answer."""

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("Ann's details are on file [1].")])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        yield "Ann's details are on file [1]."

    settings = replace(AgentSettings("ag_x", 1, [PromptFragment("You help.")], "test-model"), redact_pii=True)
    req = TurnRequest("t2", "th2", settings, [], user_turn="Who is Ann?", kb_ids=["kb_1"])
    ports = KernelPorts(model=FunctionModel(reply, stream_function=stream), tools=Tools(), knowledge=Knowledge())  # type: ignore[arg-type]
    events = [e async for e in run_turn(req, ports)]
    [ready] = [e for e in events if isinstance(e, CitationsReady)]
    finished = events[-1]
    assert isinstance(finished, TurnFinished)
    for cited in (ready.citations, finished.result.citations):
        assert [c.passage.text for c in cited] == ["Ann Lee, SSN [SSN], [email]."], cited
