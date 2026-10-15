"""One test per kernel failure mode: wrong citations, a gated write that runs before approval, a resume that runs
different input or a new key, a rejection the model never hears, and assembly errors reaching the model."""

from __future__ import annotations

from typing import Any

from ops_agent_kernel.events import CitationsReady, KernelEvent, TurnFinished
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
from tests.conftest import scripted_model

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

    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Passage]:
        return self.passages[:k]


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
