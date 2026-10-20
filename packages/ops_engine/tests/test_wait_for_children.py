"""Run workflow waiting for its children (c-263) on an in-memory checkpointer and journal, by failure mode: the
children's results never reach the parent; a failed child fails the parent or drops out of the list; a batch size is
ignored and every child starts at once; a parent waits for ever on a child that never ends; a resume after the worker
died starts children again or loses the step's attempt."""

from __future__ import annotations

import contextlib
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ops_engine import default_registry
from ops_engine.compiler import channel, compile_definition
from ops_engine.definition import parse, validate
from ops_engine.journal import MemoryJournal
from ops_engine.ports import EnginePorts, StartedRun

from .test_compiler import FakeReviews, FakeTools, KillAfter, Killed, config

ITEMS = {"files": [{"name": "a.pdf"}, {"name": "b.pdf"}, {"name": "c.pdf"}, {"name": "d.pdf"}, {"name": "e.pdf"}]}


class Children:
    """Child runs keyed as the host keys them; a test ends a child by setting its status, outcome and output."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.starts = 0
        self.output_reads = 0

    async def start(self, parent_run_id: str, workflow: str, input: dict[str, Any], key: str) -> StartedRun:
        if key in self.rows:
            return StartedRun(self.rows[key]["runId"], False)
        self.starts += 1
        self.rows[key] = {"runId": f"child{len(self.rows)}", "status": "running", "outcome": None, "output": None}
        return StartedRun(self.rows[key]["runId"], True)

    async def children(self, parent_run_id: str, key_prefix: str, *, outputs: bool = False) -> list[dict[str, Any]]:
        self.output_reads += outputs
        found = [
            {"index": int(k[len(key_prefix) :]), **row, "output": row["output"] if outputs else None}
            for k, row in self.rows.items()
            if k.startswith(key_prefix)
        ]
        return sorted(found, key=lambda c: c["index"])

    def end(self, index: int, outcome: str = "read", status: str = "succeeded") -> None:
        row = next(r for k, r in self.rows.items() if k.endswith(f":{index}"))
        row |= {"status": status, "outcome": outcome, "output": {"file": index}}

    def unfinished(self) -> int:
        return sum(1 for r in self.rows.values() if r["status"] == "running")


def definition(**settings: Any) -> Any:
    start = {"workflow": "read_one", "forEach": "$.input.files", "input": {"name": "$.item.name"}, "wait": True}
    ports = ["done", "error", *(["timeout"] if settings.get("timeoutHours") else [])]
    return parse(
        {
            "schemaVersion": 2,
            "id": "letters",
            "name": "Letters",
            "nodes": [
                {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "name": "in"},
                {
                    "id": "read",
                    "type": "ops.action.workflow",
                    "typeVersion": 1,
                    "name": "read",
                    "parameters": start | settings,
                },
                *({"id": p, "type": "ops.flow.end", "typeVersion": 1, "name": p} for p in ports),
            ],
            "connections": [
                {"from": {"node": "in", "port": "payload"}, "to": {"node": "read", "port": "in"}},
                *({"from": {"node": "read", "port": p}, "to": {"node": p, "port": "in"}} for p in ports),
            ],
        }
    )


def build(d: Any, runs: Children, journal: MemoryJournal, saver: InMemorySaver, kill: str | None = None) -> Any:
    ports = EnginePorts(tools=FakeTools(), reviews=FakeReviews(), runs=runs)
    if kill:
        ports.hooks = KillAfter(kill)
    return compile_definition(d, default_registry(), ports=ports, journal=journal, checkpointer=saver)


async def step(g: Any, run: str) -> dict[str, Any] | None:
    return (await g.aget_state(config(run))).values.get(channel("read"))


async def resume(g: Any, run: str, value: dict[str, Any] | None = None) -> None:
    await g.ainvoke(Command(resume=value or {"child": "any"}), config(run), durability="sync")


async def test_the_parent_goes_on_once_all_ended_with_each_result_in_item_order_and_a_failed_one_listed() -> None:
    d = definition()
    assert validate(d, default_registry()) == []
    runs, journal, saver = Children(), MemoryJournal(), InMemorySaver()
    g = build(d, runs, journal, saver)
    await g.ainvoke({"input": ITEMS}, config("w1"), durability="sync")
    assert (await g.aget_state(config("w1"))).interrupts and runs.starts == 5
    for i in (4, 0, 2, 1):
        runs.end(i)
        await resume(g, "w1")
        assert await step(g, "w1") is None, "it waits while a child is unfinished"
    runs.end(3, outcome="failed", status="failed")
    await resume(g, "w1")
    env = await step(g, "w1")
    assert env is not None and env["port"] == "done", env
    assert [(c["index"], c["outcome"]) for c in env["out"]["children"]] == [
        (0, "read"),
        (1, "read"),
        (2, "read"),
        (3, "failed"),
        (4, "read"),
    ]
    assert env["out"]["counts"] == {"read": 4, "failed": 1} and runs.starts == 5
    assert env["out"]["children"][0]["output"] == {"file": 0} and runs.output_reads == 1, (
        "outputs read once, at the end"
    )
    assert [r.status for r in journal.rows.values() if r.node_id == "read"] == ["ok"], "one attempt, waited in"


async def test_a_batch_of_two_never_has_three_children_unfinished_and_all_five_are_collected() -> None:
    runs, journal, saver = Children(), MemoryJournal(), InMemorySaver()
    g = build(definition(batchSize=2), runs, journal, saver)
    await g.ainvoke({"input": ITEMS}, config("w2"), durability="sync")
    most = runs.unfinished()
    for i in range(5):
        runs.end(i)
        await resume(g, "w2")
        most = max(most, runs.unfinished())
    env = await step(g, "w2")
    assert most <= 2 and env is not None and env["port"] == "done" and len(env["out"]["children"]) == 5, (most, env)


async def test_a_timeout_before_the_last_child_leaves_by_timeout_with_the_rest_named() -> None:
    runs, journal, saver = Children(), MemoryJournal(), InMemorySaver()
    d = definition(timeoutHours=1, batchSize=4)
    g = build(d, runs, journal, saver)
    await g.ainvoke({"input": ITEMS}, config("w3"), durability="sync")
    runs.end(0)
    await resume(g, "w3")
    await resume(g, "w3", {"timeout": True})
    env = await step(g, "w3")
    assert env is not None and env["port"] == "timeout", env
    assert [c["index"] for c in env["out"]["children"]] == [0]
    assert len(env["out"]["waiting"]) == 4 and env["out"]["notStarted"] == 0, env["out"]


async def test_a_worker_that_dies_while_the_parent_waits_starts_no_child_twice_and_keeps_the_attempt() -> None:
    runs, journal, saver = Children(), MemoryJournal(), InMemorySaver()
    await build(definition(), runs, journal, saver).ainvoke({"input": ITEMS}, config("w4"), durability="sync")
    for i in range(5):
        runs.end(i)
    with contextlib.suppress(Killed):
        await resume(build(definition(), runs, journal, saver, kill="read"), "w4")
    g = build(definition(), runs, journal, saver)
    await g.ainvoke(None, config("w4"), durability="sync")
    env = await step(g, "w4")
    assert env is not None and env["port"] == "done" and runs.starts == 5, (env, runs.starts)
    assert [r.status for r in journal.rows.values() if r.node_id == "read"] == ["ok"], journal.rows
