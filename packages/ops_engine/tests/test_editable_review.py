"""A review step can let its reviewer correct a value before approving (`editable`): what a document read found, say.
By failure mode: the reviewer is not shown the value; a correction is not what the next step reads; an approval with
no correction loses the original."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ops_engine import default_registry
from ops_engine.compiler import channel, compile_definition
from ops_engine.definition import parse, validate
from ops_engine.journal import MemoryJournal
from ops_engine.ports import EnginePorts

from .test_compiler import FakeReviews, FakeTools, config

READ = [
    {"values": {"name": "Marcus Bell", "amount": 3250.0}},
    {"values": {"name": "Priya Natarajan", "amount": 12400.0}},
]

FLOW = parse(
    {
        "schemaVersion": 2,
        "id": "check_read",
        "nodes": [
            {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {
                "id": "check",
                "type": "ops.flow.humanReview",
                "typeVersion": 1,
                "parameters": {"title": "Check the read", "summary": "$.input", "editable": "$.input.records"},
            },
            {
                "id": "done",
                "type": "ops.flow.end",
                "typeVersion": 1,
                "parameters": {"outcome": "checked", "output": "$.nodes.check.out.edited"},
            },
            {"id": "no", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "rejected"}},
        ],
        "connections": [
            {"from": {"node": "in", "port": "payload"}, "to": {"node": "check", "port": "in"}},
            {"from": {"node": "check", "port": "approve"}, "to": {"node": "done", "port": "in"}},
            {"from": {"node": "check", "port": "reject"}, "to": {"node": "no", "port": "in"}},
        ],
    }
)


async def run(resume: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    assert validate(FLOW, default_registry()) == []
    g = compile_definition(
        FLOW,
        default_registry(),
        ports=EnginePorts(tools=FakeTools(), reviews=FakeReviews()),
        journal=MemoryJournal(),
        checkpointer=InMemorySaver(),
    )
    await g.ainvoke({"input": {"records": READ}}, config("e1"), durability="sync")
    paused = (await g.aget_state(config("e1"))).interrupts[0].value
    await g.ainvoke(Command(resume=resume), config("e1"), durability="sync")
    return paused, (await g.aget_state(config("e1"))).values[channel("done")]["out"]["output"]


async def test_the_reviewer_sees_the_editable_value_and_the_next_step_reads_the_correction() -> None:
    fixed = [{"values": {"name": "Marcus Bell", "amount": 325.0}}, READ[1]]
    paused, out = await run({"decision": "approved", "edited": fixed})
    assert paused["editable"] == {"path": "$.input.records", "value": READ}
    assert out == fixed


async def test_an_approval_with_no_correction_keeps_what_was_read() -> None:
    _, out = await run({"decision": "approved"})
    assert out == READ
