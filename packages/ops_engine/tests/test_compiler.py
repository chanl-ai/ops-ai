"""The v2 compiler and its node wrapper on an in-memory checkpointer and journal, by failure mode: a run that does not
reach its review or end, a re-run that calls a recorded tool again, a dangling write sent twice, a failing read not
retried by its effects class, and an engine that reaches into ops_agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ops_engine import default_registry
from ops_engine.compiler import WriteInDoubtError, channel, compile_definition
from ops_engine.definition import parse, validate
from ops_engine.journal import MemoryJournal, StepRow
from ops_engine.ports import Access, AgentRequest, AgentResult, EnginePorts, Faults, ToolResult

BASIC = parse((Path(__file__).parent / "fixtures" / "basic.yaml").read_text())
PAYLOAD = {"customerId": "C-1", "amount": 250}


class Killed(BaseException):
    """Stands in for SIGKILL: not an Exception, so nothing in the wrapper catches it."""


class FakeTools:
    def __init__(
        self,
        access: Access = "read",
        fail: int = 0,
        recorded: ToolResult | None = None,
        lost: BaseException | None = None,
    ) -> None:
        self.calls: list[str] = []
        self._access: Access = access
        self._fail, self.recorded, self._lost = fail, recorded, lost

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.calls.append(key)
        if self._lost is not None:
            # The gateway ran it, and the answer never came back: a kill or a timeout mid-write.
            lost, self._lost = self._lost, None
            self.recorded = ToolResult(True, {"ref": "H-1"})
            raise lost
        if self._fail:
            self._fail -= 1
            raise ConnectionError("gateway unreachable")
        return ToolResult(True, {"id": input.get("customer_id"), "name": "Ana"})

    async def access(self, operation: str) -> Access:
        return self._access

    async def mint(self, run_id: str, call: dict[str, Any], approval: dict[str, Any]) -> str | None:
        return None

    async def find(self, key: str, operation: str) -> ToolResult | None:
        return self.recorded if key in self.calls or (self.recorded is not None and not self.calls) else None


class FakeReviews:
    async def open(self, run_id: str, node_id: str, iteration: int, payload: dict[str, Any]) -> str:
        return f"{run_id}:{node_id}:{iteration}"


class KillAfter:
    def __init__(self, node: str) -> None:
        self.node, self.armed = node, True

    async def after_step(self, run_id: str, node_id: str, status: str) -> None:
        if self.armed and node_id == self.node:
            self.armed = False
            raise Killed


def config(run: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run, "run_id": run, "lease_generation": 1}}


def build(
    tools: FakeTools, journal: MemoryJournal, saver: InMemorySaver, *, kill: str | None = None, lookup: bool = True
) -> Any:
    ports = EnginePorts(tools=tools, reviews=FakeReviews(), faults=Faults(ignore_recorded=not lookup))
    if kill:
        ports.hooks = KillAfter(kill)
    return compile_definition(BASIC, default_registry(), ports=ports, journal=journal, checkpointer=saver)


def test_the_basic_definition_passes_its_checks() -> None:
    assert validate(BASIC, default_registry()) == []


async def test_runs_to_the_review_and_ends_on_the_chosen_port() -> None:
    tools, journal, saver = FakeTools(), MemoryJournal(), InMemorySaver()
    g = build(tools, journal, saver)
    await g.ainvoke({"input": PAYLOAD}, config("r1"), durability="sync")
    state = await g.aget_state(config("r1"))
    assert state.interrupts and state.interrupts[0].value["review_id"] == "r1:review:1"
    await g.ainvoke(Command(resume={"decision": "approved", "by": "m"}), config("r1"), durability="sync")
    values = (await g.aget_state(config("r1"))).values
    assert values[channel("approved")]["out"]["outcome"] == "approved"
    assert values[channel("review")]["port"] == "approve"
    assert values[channel("lookup")]["out"] == {"id": "C-1", "name": "Ana"}
    steps = {(r.node_id, r.status) for r in journal.rows.values()}
    assert ("review", "ok") in steps and ("lookup", "ok") in steps
    # Each step names its node type, which Activity lists tool calls by.
    assert {r.node_id: r.node_type for r in journal.rows.values()}["lookup"] == "ops.action.tool"


async def test_a_small_amount_takes_the_false_port() -> None:
    tools, journal, saver = FakeTools(), MemoryJournal(), InMemorySaver()
    g = build(tools, journal, saver)
    await g.ainvoke({"input": {"customerId": "C-1", "amount": 5}}, config("r2"), durability="sync")
    values = (await g.aget_state(config("r2"))).values
    assert values[channel("small")]["out"]["outcome"] == "small" and tools.calls == []


@pytest.mark.parametrize(("lookup", "calls"), [(True, 1), (False, 2)])
async def test_a_crash_after_the_tool_step_returns_its_recorded_output(lookup: bool, calls: int) -> None:
    """The kill lands after the step row is finished and before LangGraph saves the step, so LangGraph runs the node
    again. With the recorded-output lookup the tool is called once; without it, twice (the non-vacuous case)."""
    tools, journal, saver = FakeTools(), MemoryJournal(), InMemorySaver()
    with pytest.raises(Killed):
        await build(tools, journal, saver, kill="lookup", lookup=lookup).ainvoke(
            {"input": PAYLOAD}, config("r3"), durability="sync"
        )
    g = build(tools, journal, saver, lookup=lookup)
    await g.ainvoke(None, config("r3"), durability="sync")
    assert len(tools.calls) == calls
    assert (await g.aget_state(config("r3"))).interrupts, "the run reached its review after the crash"


@pytest.mark.parametrize(
    ("recorded", "port"),
    [(ToolResult(True, {"ref": "H-1"}), "ok"), (None, "error")],
)
async def test_a_dangling_write_is_reconciled_by_its_key_and_never_sent_again(
    recorded: ToolResult | None, port: str
) -> None:
    tools, journal, saver = FakeTools(access="write", recorded=recorded), MemoryJournal(), InMemorySaver()
    with pytest.raises(Killed):
        # Killed after the if step: the checkpoint holds fields and big, the tool step has not run.
        await build(tools, journal, saver, kill="big").ainvoke({"input": PAYLOAD}, config("r4"), durability="sync")
    # The write's process died mid-call: its attempt row is left running.
    await journal.begin(StepRow("r4", "lookup", 1, 1, "running", "write", "r4:lookup:1:1", input={}))
    g = build(tools, journal, saver)
    await g.ainvoke(None, config("r4"), durability="sync")
    assert tools.calls == []
    values = (await g.aget_state(config("r4"))).values
    assert values[channel("lookup")]["port"] == port


async def test_a_read_is_retried_and_a_write_is_not() -> None:
    reads, journal = FakeTools(fail=2), MemoryJournal()
    await build(reads, journal, InMemorySaver()).ainvoke({"input": PAYLOAD}, config("r5"), durability="sync")
    assert [r.status for r in await journal.steps("r5", "lookup", 1)] == ["error", "error", "ok"]
    writes, journal = FakeTools(access="write", fail=1), MemoryJournal()
    g = build(writes, journal, InMemorySaver())
    await g.ainvoke({"input": PAYLOAD}, config("r6"), durability="sync")
    assert len(writes.calls) == 1
    assert (await g.aget_state(config("r6"))).values[channel("failed")]["out"]["outcome"] == "tool_failed"


async def test_a_worker_killed_mid_write_finds_the_write_by_its_key_and_never_sends_it_again() -> None:
    tools, journal, saver = FakeTools(access="write", lost=Killed()), MemoryJournal(), InMemorySaver()
    with pytest.raises(Killed):
        await build(tools, journal, saver).ainvoke({"input": PAYLOAD}, config("r7"), durability="sync")
    assert [r.status for r in await journal.steps("r7", "lookup", 1)] == ["running"]
    g = build(tools, journal, saver)
    await g.ainvoke(None, config("r7"), durability="sync")
    assert tools.calls == ["r7:lookup:1:1"], "sent once"
    assert (await g.aget_state(config("r7"))).values[channel("lookup")]["port"] == "ok"


async def test_a_write_whose_call_raises_is_reconciled_not_failed() -> None:
    tools, journal = FakeTools(access="write", lost=TimeoutError()), MemoryJournal()
    g = build(tools, journal, InMemorySaver())
    await g.ainvoke({"input": PAYLOAD}, config("r8"), durability="sync")
    assert tools.calls == ["r8:lookup:1:1"]
    assert (await g.aget_state(config("r8"))).values[channel("lookup")]["port"] == "ok"


async def test_a_write_still_running_at_the_gateway_is_neither_done_nor_sent_again() -> None:
    tools = FakeTools(access="write", recorded=ToolResult(False, pending=True))
    journal, saver = MemoryJournal(), InMemorySaver()
    with pytest.raises(Killed):
        await build(tools, journal, saver, kill="big").ainvoke({"input": PAYLOAD}, config("r9"), durability="sync")
    await journal.begin(StepRow("r9", "lookup", 1, 1, "running", "write", "r9:lookup:1:1", input={}))
    with pytest.raises(WriteInDoubtError):
        await build(tools, journal, saver).ainvoke(None, config("r9"), durability="sync")
    assert tools.calls == []
    assert [r.status for r in await journal.steps("r9", "lookup", 1)] == ["running"]


async def test_an_error_port_is_recorded_as_an_error_and_returned_on_a_rerun() -> None:
    tools, journal, saver = FakeTools(access="write", fail=1), MemoryJournal(), InMemorySaver()
    with pytest.raises(Killed):
        await build(tools, journal, saver, kill="lookup").ainvoke({"input": PAYLOAD}, config("r10"), durability="sync")
    (row,) = await journal.steps("r10", "lookup", 1)
    assert (row.status, row.port) == ("error", "error")
    await build(tools, journal, saver).ainvoke(None, config("r10"), durability="sync")
    assert len(tools.calls) == 1


def test_an_approved_write_reading_a_later_node_is_refused() -> None:
    raw = BASIC.wire()
    for n in raw["nodes"]:
        if n["id"] == "review":
            n["parameters"]["approves"] = "lookup"  # lookup runs before the review: it does not follow it
        if n["id"] == "lookup":
            n["parameters"]["approvedBy"] = "review"
    checks = {(c["node"], c["code"]) for c in validate(parse(raw), default_registry())}
    assert ("review", "approval_order") in checks and ("lookup", "approval_order") in checks


async def test_a_review_will_not_approve_a_write_with_an_empty_input() -> None:
    raw: dict[str, Any] = {
        "schemaVersion": 2,
        "id": "w",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1},
            {"id": "review", "type": "ops.flow.humanReview", "typeVersion": 1, "parameters": {"approves": "hold"}},
            {
                "id": "hold",
                "type": "ops.action.tool",
                "typeVersion": 1,
                "parameters": {
                    "operation": "place_hold",
                    "input": {"amount": "$.input.amount"},
                    "approvedBy": "review",
                },
            },
            *({"id": e, "type": "ops.flow.end", "typeVersion": 1} for e in ("ok", "no", "bad", "err")),
        ],
        "connections": [
            {"from": {"node": a, "port": p}, "to": {"node": b, "port": "in"}}
            for a, p, b in [
                ("start", "payload", "review"),
                ("review", "approve", "hold"),
                ("review", "reject", "no"),
                ("hold", "ok", "ok"),
                ("hold", "refused", "bad"),
                ("hold", "error", "err"),
            ]
        ],
    }
    d = parse(raw)
    assert validate(d, default_registry()) == []
    g = compile_definition(
        d,
        default_registry(),
        ports=EnginePorts(tools=FakeTools(access="write"), reviews=FakeReviews()),
        journal=MemoryJournal(),
        checkpointer=InMemorySaver(),
    )
    with pytest.raises(ValueError, match="amount is empty"):
        await g.ainvoke({"input": {}}, config("r11"), durability="sync")


class FakeAgents:
    def __init__(self, answer: AgentResult) -> None:
        self.answer = answer
        self.requests: list[AgentRequest] = []

    async def turn(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        return self.answer


AGENT_FLOW: dict[str, Any] = {
    "schemaVersion": 2,
    "id": "summary",
    "nodes": [
        {"id": "start", "type": "ops.trigger.request", "typeVersion": 1},
        {
            "id": "summarise",
            "type": "ops.ai.agent",
            "typeVersion": 1,
            "parameters": {
                "agent": "ag_advisor",
                "prompt": "Summarise the customer.",
                "input": {"customerId": "$.input.customerId"},
                "outputSchema": {"type": "object", "required": ["customerId", "summary"]},
            },
        },
        {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "summarised"}},
        {"id": "failed", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "failed"}},
    ],
    "connections": [
        {"from": {"node": "start", "port": "payload"}, "to": {"node": "summarise", "port": "in"}},
        {"from": {"node": "summarise", "port": "ok"}, "to": {"node": "done", "port": "in"}},
        {"from": {"node": "summarise", "port": "error"}, "to": {"node": "failed", "port": "in"}},
    ],
}


@pytest.mark.parametrize(
    ("answer", "port"),
    [
        (AgentResult(True, {"customerId": "CUS-1", "summary": "A retail customer."}), "ok"),
        (AgentResult(False, error="the answer did not match the schema", code="schema_error"), "error"),
        # customer_summary on shared, 2026-10-18: a port answered ok with no output, and the step took ok with null.
        (AgentResult(True, None), "error"),
    ],
)
async def test_an_agent_step_runs_a_turn_by_schema_and_a_mismatch_takes_the_error_port(
    answer: AgentResult, port: str
) -> None:
    d = parse(AGENT_FLOW)
    assert validate(d, default_registry()) == []
    agents = FakeAgents(answer)
    ports = EnginePorts(tools=FakeTools(), reviews=FakeReviews(), agents=agents)
    g = compile_definition(d, default_registry(), ports=ports, journal=MemoryJournal(), checkpointer=InMemorySaver())
    await g.ainvoke({"input": {"customerId": "CUS-1"}}, config("r12"), durability="sync")
    env = (await g.aget_state(config("r12"))).values[channel("summarise")]
    assert env["port"] == port
    (req,) = agents.requests
    assert req.turn_id == "r12:summarise:1" and req.output_schema is not None and '"CUS-1"' in req.message
    if port == "ok":
        assert env["out"] == {"customerId": "CUS-1", "summary": "A retail customer."}


async def test_a_dangling_write_is_reconciled_even_if_its_operation_is_now_a_read() -> None:
    """The row's own effects decide: an operation reclassified to read after a crash must not get its write resent."""
    tools, journal, saver = FakeTools(access="read", recorded=None), MemoryJournal(), InMemorySaver()
    with pytest.raises(Killed):
        await build(tools, journal, saver, kill="big").ainvoke({"input": PAYLOAD}, config("r13"), durability="sync")
    await journal.begin(StepRow("r13", "lookup", 1, 1, "running", "write", "r13:lookup:1:1", input={}))
    g = build(tools, journal, saver)
    await g.ainvoke(None, config("r13"), durability="sync")
    assert tools.calls == [], "a running write is never sent again"
    assert (await g.aget_state(config("r13"))).values[channel("lookup")]["port"] == "error"


def test_a_parameter_error_names_its_field() -> None:
    raw = BASIC.wire()
    for n in raw["nodes"]:
        if n["id"] == "lookup":
            del n["parameters"]["operation"]  # required at the top: the missing property is the field
            n["parameters"]["input"] = "not an object"  # wrong type under a path: the first segment is the field
    found = {(c["code"], c["field"]) for c in validate(parse(raw), default_registry()) if c["node"] == "lookup"}
    assert ("invalid_parameter", "operation") in found and ("invalid_parameter", "input") in found
    others = [c for c in validate(parse(raw), default_registry()) if c["code"] != "invalid_parameter"]
    assert all(c["field"] is None for c in others)


async def test_an_agent_steps_own_model_and_tool_cap_reach_its_turn() -> None:
    # A step on an agent shared with chat needs its own model and a bound on its tool calls (customer_summary on shared,
    # 2026-10-18: the chat alias's low effort looped on tools); without them reaching the turn, neither applies.
    raw = json.loads(json.dumps(AGENT_FLOW))
    step = next(n for n in raw["nodes"] if n["id"] == "summarise")
    step["parameters"] |= {"model": "gpt-5.5-low", "maxToolCalls": 2}
    d = parse(raw)
    assert validate(d, default_registry()) == []
    agents = FakeAgents(AgentResult(True, {"customerId": "CUS-1", "summary": "A retail customer."}))
    ports = EnginePorts(tools=FakeTools(), reviews=FakeReviews(), agents=agents)
    g = compile_definition(d, default_registry(), ports=ports, journal=MemoryJournal(), checkpointer=InMemorySaver())
    await g.ainvoke({"input": {"customerId": "CUS-1"}}, config("r13"), durability="sync")
    (req,) = agents.requests
    assert (req.model_alias, req.max_tool_calls) == ("gpt-5.5-low", 2)
