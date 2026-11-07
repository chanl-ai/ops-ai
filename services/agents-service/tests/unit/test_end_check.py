"""The end-clean check: a finished answer with an error code, a stray last word, a question after reads that all
succeeded, or uncited knowledge gets one correction call naming the defect.

One test per way it breaks: a code reaches the person (F4); the correction loops (F5); an id or a capitalised word is
taken for a code (F6); a stray "ok" stays; a question after successful reads stays, or a fair question with no lookup
is "corrected"; knowledge used without a citation stays, or a tool answer is forced to cite."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agent_kernel import answer_check
from ops_agent_kernel.events import KernelEvent, TextReplaced, TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.types import AgentSettings, Passage, PromptFragment, ToolGrant, TurnRequest, TurnResult

CASES = ToolGrant(
    "find_cases", "ops", "Find cases", "read", {"type": "object", "properties": {"search": {"type": "string"}}}
)
POLICY = Passage("doc_1", "Credit policy", "4 Documents", "v1", "Two years of tax returns are required.", "kb_risk")
SETTINGS = AgentSettings("ag_ops", 1, [PromptFragment("You are Ops Assistant.")], "test-model", 6, 8, end_check=True)


class Tools:
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        return ToolOutcome(True, {"cards": [], "summary": "2 case(s) match"})


class Knowledge:
    def __init__(self, passages: list[Passage]) -> None:
        self.passages = passages

    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Passage]:
        return self.passages


class Writer:
    """Answers the person's turn with `first` (after one find_cases when `read`), and a correction prompt with
    `fixed`; counts the model calls."""

    def __init__(self, first: str, fixed: str, *, read: bool = False) -> None:
        self.first, self.fixed, self.read = first, fixed, read
        self.calls = 0
        self.corrections: list[str] = []

    def _reply(self, messages: list[ModelMessage]) -> str | tuple[str, dict[str, Any]]:
        self.calls += 1
        last = messages[-1]
        asked = (
            [p.content for p in last.parts if isinstance(p, UserPromptPart)] if isinstance(last, ModelRequest) else []
        )
        if asked and str(asked[0]).startswith("Your reply "):
            self.corrections.append(str(asked[0]))
            return self.fixed
        called = any(isinstance(p, ToolCallPart) for m in messages for p in getattr(m, "parts", []))
        return ("find_cases", {"search": "open"}) if self.read and not called else self.first

    def model(self) -> FunctionModel:
        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            out = self._reply(messages)
            return ModelResponse(parts=[TextPart(out) if isinstance(out, str) else ToolCallPart(*out)])

        async def stream(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
            out = self._reply(messages)
            if isinstance(out, str):
                yield out
            else:
                yield {0: DeltaToolCall(name=out[0], json_args=json.dumps(out[1]))}

        return FunctionModel(respond, stream_function=stream)


async def run(
    writer: Writer, *, tools: list[ToolGrant], passages: list[Passage] | None = None
) -> tuple[list[KernelEvent], TurnResult]:
    req = TurnRequest("t1", "th1", SETTINGS, tools, user_turn="What needs me?", kb_ids=["kb_risk"] if passages else [])
    ports = KernelPorts(model=writer.model(), tools=Tools(), knowledge=Knowledge(passages or []))
    events = [e async for e in run_turn(req, ports)]
    last = events[-1]
    assert isinstance(last, TurnFinished)
    return events, last.result


async def test_an_error_code_is_corrected_once_into_words() -> None:
    # F4: the code reached the person as "Error: CONNECTION_NOT_LINKED — Salesforce needs ...".
    writer = Writer("Error: CONNECTION_NOT_LINKED. Salesforce needs your sign-in.", "Salesforce needs your sign-in.")
    events, result = await run(writer, tools=[])
    assert result.text == "Salesforce needs your sign-in."
    assert any(isinstance(e, TextReplaced) and e.text == result.text for e in events)
    assert writer.calls == 2 and "CONNECTION_NOT_LINKED" in writer.corrections[0]


async def test_a_correction_that_repeats_the_defect_is_not_retried() -> None:
    # F5: one correction at most; one that still carries the code leaves the answer as it was.
    writer = Writer("RATE_LIMITED, try later.", "RATE_LIMITED again.")
    _, result = await run(writer, tools=[])
    assert writer.calls == 2
    assert result.text == "RATE_LIMITED, try later."


async def test_ids_and_capitalised_words_are_not_error_codes() -> None:
    # F6: a record id or a notice's own title is not a code, so no correction call is made.
    writer = Writer("Customer CUS-1002 has a NOTICE OF LEVY, case SYN-2026-0006 [1].", "unused")
    _, result = await run(writer, tools=[])
    assert writer.calls == 1 and result.text.startswith("Customer CUS-1002")


async def test_a_record_id_or_tool_name_in_the_reply_is_corrected() -> None:
    # A live reply read "the annual review at 2:00 pm (case_0eef29f68716) ... (my_human_tasks)".
    writer = Writer("The review is at 2:00 pm (case_0eef29f68716).", "The Okafor review is at 2:00 pm.", read=True)
    _, result = await run(writer, tools=[CASES])
    assert writer.calls == 3 and result.text == "The Okafor review is at 2:00 pm."
    assert answer_check.internal_name("Nothing waits for you (find_cases).", frozenset({"find_cases"})) == "find_cases"


async def test_a_stray_ok_at_the_end_is_corrected() -> None:
    writer = Writer("Two cases are open for you.\n\nok", "Two cases are open for you.")
    _, result = await run(writer, tools=[])
    assert writer.calls == 2 and result.text == "Two cases are open for you."


async def test_a_sentence_that_ends_in_done_is_not_stray() -> None:
    # "...until the review is done." was taken for a stray "done" and corrected away.
    writer = Writer("The control counts as not tested until the review is done.", "unused")
    _, result = await run(writer, tools=[])
    assert writer.calls == 1 and result.text.endswith("is done.")


async def test_a_question_after_reads_that_succeeded_is_corrected() -> None:
    writer = Writer("I found two cases. Want me to show the team's tasks too?", "Two cases need you.", read=True)
    _, result = await run(writer, tools=[CASES])
    assert writer.calls == 3 and result.text == "Two cases need you."
    assert "every lookup succeeded" in writer.corrections[0]


async def test_an_offer_to_read_more_after_failed_reads_is_corrected() -> None:
    # A live reply after three failed reads: "I can retry now using the platform's defaults ... proceed?"
    class Failing(Tools):
        async def execute(
            self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
        ) -> ToolOutcome:
            return ToolOutcome(False, {"error": "The team has no file named open."})

    writer = Writer(
        "The reads failed; I can retry with your own open cases. Proceed?", "Nothing could be read.", read=True
    )
    req = TurnRequest("t1", "th1", SETTINGS, [CASES], user_turn="What needs me?")
    events = [
        e async for e in run_turn(req, KernelPorts(model=writer.model(), tools=Failing(), knowledge=Knowledge([])))
    ]
    result = events[-1]
    assert isinstance(result, TurnFinished)
    assert writer.calls == 3 and result.result.text == "Nothing could be read.", result.result.text


async def test_a_question_with_no_lookup_is_left_alone() -> None:
    # A vague ask may get one question back when nothing was looked up.
    writer = Writer("Which team's cases do you mean?", "unused")
    _, result = await run(writer, tools=[CASES])
    assert writer.calls == 1 and result.text.endswith("?")


async def test_knowledge_used_without_a_citation_is_corrected() -> None:
    writer = Writer("Two years of tax returns are required.", "Two years of tax returns are required [1].")
    _, result = await run(writer, tools=[], passages=[POLICY])
    assert writer.calls == 2 and [c.n for c in result.citations] == [1]


async def test_a_tool_answer_in_a_knowledge_thread_is_not_forced_to_cite() -> None:
    writer = Writer("Two cases match.", "unused", read=True)
    _, result = await run(writer, tools=[CASES], passages=[POLICY])
    assert writer.calls == 2 and result.text == "Two cases match."


def test_the_check_reads_codes_only_in_capitals() -> None:
    assert answer_check.error_code("call find_cases with search_knowledge") is None
    assert answer_check.error_code('{"error": "FORBIDDEN"}') == "FORBIDDEN"
    assert answer_check.error_code("Error: Unknown file") is None
