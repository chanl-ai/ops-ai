"""A review option's write that fails goes back to the same review (c-210, the levy hold), by failure mode: the
reviewer's edited amount is not what is sent; the failed write ends the run or is sent again; the second decision's
call is bound to the first iteration's step, so it goes without its approval."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ops_engine import default_registry
from ops_engine.compiler import channel, compile_definition
from ops_engine.definition import parse, validate
from ops_engine.journal import MemoryJournal
from ops_engine.ports import Access, EnginePorts, ToolResult

from .test_compiler import FakeReviews, config

CASE = parse(
    {
        "schemaVersion": 2,
        "id": "case",
        "name": "Case",
        "nodes": [
            {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "name": "Request"},
            {
                "id": "review",
                "type": "ops.flow.humanReview",
                "typeVersion": 1,
                "name": "Review",
                "parameters": {
                    "title": "Levy",
                    "options": [
                        {"name": "hold", "call": {"node": "hold"}, "inputs": [{"name": "amount", "type": "number"}]},
                        {"name": "flag"},
                    ],
                },
            },
            {
                "id": "hold",
                "type": "ops.action.tool",
                "typeVersion": 1,
                "name": "Hold",
                "parameters": {
                    "operation": "place_hold",
                    "input": {"account_id": "$.input.account", "amount": "$.input.amount"},
                    "approvedBy": "review",
                },
            },
            {"id": "held", "type": "ops.flow.end", "typeVersion": 1, "name": "Held", "parameters": {"outcome": "held"}},
            {"id": "flagged", "type": "ops.flow.end", "typeVersion": 1, "name": "Flag", "parameters": {"outcome": "f"}},
        ],
        "connections": [
            {"from": {"node": "in", "port": "payload"}, "to": {"node": "review", "port": "in"}},
            {"from": {"node": "review", "port": "hold"}, "to": {"node": "hold", "port": "in"}},
            {"from": {"node": "review", "port": "flag"}, "to": {"node": "flagged", "port": "in"}},
            {"from": {"node": "hold", "port": "ok"}, "to": {"node": "held", "port": "in"}},
            {"from": {"node": "hold", "port": "refused"}, "to": {"node": "review", "port": "in"}},
            {"from": {"node": "hold", "port": "error"}, "to": {"node": "review", "port": "in"}},
        ],
    }
)


class Bank:
    """place_hold as the fake bank answers it: over the balance is a 422, the gateway's answer an error output."""

    def __init__(self, balance: float) -> None:
        self.balance = balance
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.sent.append((key, dict(input)))
        if float(input["amount"]) > self.balance:
            return ToolResult(False, {"status": 422}, reason="the operation returned an error")
        return ToolResult(True, {"id": "HLD-1"})

    async def access(self, operation: str) -> Access:
        return "write"

    async def mint(self, run_id: str, call: dict[str, Any], approval: dict[str, Any]) -> str | None:
        return "token"

    async def find(self, key: str, operation: str) -> ToolResult | None:
        return None


def decide(payload: dict[str, Any], amount: float) -> Command[Any]:
    """The decision engine_reviews records: the option, and its call with the reviewer's amount."""
    offered = next(o for o in payload["options"] if o["name"] == "hold")["call"]
    call = offered | {"input": offered["input"] | {"amount": amount}}
    return Command(resume={"decision": "approved", "option": "hold", "call": call, "approval": {"step": call["step"]}})


async def test_a_hold_over_the_balance_returns_to_the_review_and_the_next_decision_is_sent_once() -> None:
    assert validate(CASE, default_registry()) == []
    bank, saver = Bank(balance=2000), InMemorySaver()
    ports = EnginePorts(tools=bank, reviews=FakeReviews())
    g = compile_definition(CASE, default_registry(), ports=ports, journal=MemoryJournal(), checkpointer=saver)
    await g.ainvoke({"input": {"account": "CHQ-1", "amount": 3250}}, config("c1"), durability="sync")
    first = (await g.aget_state(config("c1"))).interrupts[0].value
    await g.ainvoke(decide(first, 9000), config("c1"), durability="sync")
    again = (await g.aget_state(config("c1"))).interrupts
    assert again and again[0].value["iteration"] == 2, "the 422 waits on the same review"
    await g.ainvoke(decide(again[0].value, 1500), config("c1"), durability="sync")
    values = (await g.aget_state(config("c1"))).values
    assert values[channel("held")]["out"]["outcome"] == "held"
    assert bank.sent == [
        ("c1:hold:1:1", {"account_id": "CHQ-1", "amount": 9000}),
        ("c1:hold:2:1", {"account_id": "CHQ-1", "amount": 1500}),
    ]
