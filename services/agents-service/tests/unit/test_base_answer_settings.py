"""A knowledge base's answer settings applied to the turn's answer: an uncited answer from a base that withholds one
is replaced by the base's no-answer message, also when nothing is found; a cited answer, and a base that gives back
pieces only, are left alone. The agent's own end check is off, as it is for most agents."""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.types import (
    AgentSettings,
    BaseAnswer,
    KnowledgeFound,
    Passage,
    PromptFragment,
    TurnRequest,
    TurnResult,
)

FEES = Passage("doc_1", "Fee schedule", "Wires", "v2", "An outgoing wire costs 25.00.", "kb_fees")
MESSAGE = "I could not find that in the fee schedule. A banker will call you back."
WITHHOLDS = BaseAnswer("answer_with_citations", True, MESSAGE)
PIECES_ONLY = BaseAnswer("chunks", True, MESSAGE)
SETTINGS = AgentSettings("ag_fees", 1, [PromptFragment("You answer fee questions.")], "test-model", 6, 8)


class Tools:
    async def execute(
        self, tool: str, arguments: dict[str, object], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        return ToolOutcome(True, {})


class Knowledge:
    def __init__(self, passages: list[Passage], answer: BaseAnswer) -> None:
        self.found = KnowledgeFound(passages, {"kb_fees": answer})

    async def search(self, query: str, kb_ids: list[str]) -> list[Passage]:
        return self.found


def writer(text: str) -> FunctionModel:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(text)])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        yield text

    return FunctionModel(respond, stream_function=stream)


async def turn(answer: str, base: BaseAnswer, passages: list[Passage]) -> TurnResult:
    req = TurnRequest("t1", "th1", SETTINGS, [], user_turn="What does a wire cost?", kb_ids=["kb_fees"])
    ports = KernelPorts(model=writer(answer), tools=Tools(), knowledge=Knowledge(passages, base))
    events = [e async for e in run_turn(req, ports)]
    last = events[-1]
    assert isinstance(last, TurnFinished)
    return last.result


async def test_an_uncited_answer_from_a_withholding_base_is_replaced_by_its_message() -> None:
    result = await turn("A wire costs about 30.00, I think.", WITHHOLDS, [FEES])
    assert result.text == MESSAGE
    assert result.no_answer


async def test_a_cited_answer_from_a_withholding_base_is_kept() -> None:
    result = await turn("An outgoing wire costs 25.00 [1].", WITHHOLDS, [FEES])
    assert result.text == "An outgoing wire costs 25.00 [1]."


async def test_a_base_that_gives_back_pieces_only_never_withholds() -> None:
    result = await turn("A wire costs about 30.00, I think.", PIECES_ONLY, [FEES])
    assert result.text == "A wire costs about 30.00, I think."


async def test_nothing_found_says_the_bases_no_answer_message() -> None:
    result = await turn("Wires usually cost 30.00 at most banks.", WITHHOLDS, [])
    assert result.text == MESSAGE
