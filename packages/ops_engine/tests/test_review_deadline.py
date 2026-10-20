"""A review step's deadline (c-074): the step records when it opened and how long a person has, and one set to expire
leaves on its own `timeout` port when the host resumes it as timed out. By failure mode: the deadline's facts are not
on the waiting payload, so nothing can tell it is overdue; an expiring step has no port to leave by, so a timeout
fails the run; a step left to wait gets a port it must wire."""

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


def flow(on_timeout: str) -> Any:
    ends = [
        {"id": "ok", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "approved"}},
        {"id": "no", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "rejected"}},
    ]
    wires = [
        {"from": {"node": "in", "port": "payload"}, "to": {"node": "check", "port": "in"}},
        {"from": {"node": "check", "port": "approve"}, "to": {"node": "ok", "port": "in"}},
        {"from": {"node": "check", "port": "reject"}, "to": {"node": "no", "port": "in"}},
    ]
    if on_timeout == "expire":
        ends.append({"id": "late", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "expired"}})
        wires.append({"from": {"node": "check", "port": "timeout"}, "to": {"node": "late", "port": "in"}})
    return parse(
        {
            "schemaVersion": 2,
            "id": "deadline",
            "nodes": [
                {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
                {
                    "id": "check",
                    "type": "ops.flow.humanReview",
                    "typeVersion": 1,
                    "parameters": {"title": "Check it", "slaHours": 2, "onTimeout": on_timeout},
                },
                *ends,
            ],
            "connections": wires,
        }
    )


async def test_an_expiring_review_records_its_deadline_and_leaves_on_timeout() -> None:
    d = flow("expire")
    assert validate(d, default_registry()) == []
    g = compile_definition(
        d,
        default_registry(),
        ports=EnginePorts(tools=FakeTools(), reviews=FakeReviews()),
        journal=MemoryJournal(),
        checkpointer=InMemorySaver(),
    )
    await g.ainvoke({"input": {}}, config("t1"), durability="sync")
    paused = (await g.aget_state(config("t1"))).interrupts[0].value
    assert (paused["slaHours"], paused["onTimeout"]) == (2.0, "expire") and paused["openedAt"].endswith("Z")
    await g.ainvoke(Command(resume={"decision": "timeout", "by": "system:sla"}), config("t1"), durability="sync")
    values = (await g.aget_state(config("t1"))).values
    assert values[channel("late")]["out"]["outcome"] == "expired"
    assert values[channel("check")]["out"]["by"] == "system:sla"


def test_a_review_left_to_wait_has_no_timeout_port() -> None:
    review = default_registry().get("ops.flow.humanReview", 1)
    assert review.output_ports({"onTimeout": "wait"}) == ["approve", "reject"]
    assert review.output_ports({"onTimeout": "expire"}) == ["approve", "reject", "timeout"]
    assert review.output_ports({"onTimeout": "expire", "options": ["hold", "flag"]}) == ["hold", "flag", "timeout"]
