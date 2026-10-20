"""Start workflow (c-209) on an in-memory checkpointer and journal, by failure mode: a re-run or retry that starts a
second child for an item, a retry reconciled through the tool gateway (which never sees a start) instead of repeated,
a refusal or a bad list that still starts children, and `$.item` used where no item is."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from ops_engine import default_registry
from ops_engine.compiler import channel, compile_definition
from ops_engine.definition import parse, validate
from ops_engine.journal import MemoryJournal
from ops_engine.ports import EnginePorts, Faults, RunRefusedError, StartedRun

from .test_compiler import FakeReviews, FakeTools, KillAfter, Killed, config


def definition(start: dict[str, Any]) -> Any:
    return parse(
        {
            "schemaVersion": 2,
            "id": "intake",
            "name": "Intake",
            "nodes": [
                {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "name": "Request"},
                {"id": "open", "type": "ops.action.workflow", "typeVersion": 1, "name": "Open", "parameters": start},
                {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
                {"id": "failed", "type": "ops.flow.end", "typeVersion": 1, "name": "Failed", "parameters": {}},
            ],
            "connections": [
                {"from": {"node": "in", "port": "payload"}, "to": {"node": "open", "port": "in"}},
                {"from": {"node": "open", "port": "started"}, "to": {"node": "done", "port": "in"}},
                {"from": {"node": "open", "port": "error"}, "to": {"node": "failed", "port": "in"}},
            ],
        }
    )


PER_PERSON = {
    "workflow": "case",
    "forEach": "$.input.persons",
    "input": {"name": "$.item.name", "position": "$.index", "letter": "$.input.letter"},
}
PERSONS = {"letter": "L-1", "persons": [{"name": "Ana"}, {"name": "Bo"}, {"name": "Cy"}]}


class FakeRuns:
    """Starts one child per key, as the host's unique run key does; `refuse_at` refuses the start of that item."""

    def __init__(self, *, refuse_at: int | None = None, fail: int = 0) -> None:
        self.started: dict[str, dict[str, Any]] = {}
        self.calls = 0
        self.refuse_at, self._fail = refuse_at, fail

    async def start(self, parent_run_id: str, workflow: str, input: dict[str, Any], key: str) -> StartedRun:
        self.calls += 1
        if self._fail:
            self._fail -= 1
            raise ConnectionError("database unreachable")
        if self.refuse_at is not None and key.endswith(f":{self.refuse_at}"):
            raise RunRefusedError(f"{workflow} is paused", "workflow_paused")
        if key in self.started:
            return StartedRun(self.started[key]["id"], False)
        self.started[key] = {"id": f"child{len(self.started)}", "workflow": workflow, "input": input}
        return StartedRun(self.started[key]["id"], True)

    async def children(self, parent_run_id: str, key_prefix: str, *, outputs: bool = False) -> list[dict[str, Any]]:
        """These steps never wait for their children (test_wait_for_children.py covers waiting)."""
        return []


def build(start: dict[str, Any], runs: FakeRuns, journal: MemoryJournal, saver: InMemorySaver, **kw: Any) -> Any:
    tools = FakeTools()
    ports = EnginePorts(
        tools=tools, reviews=FakeReviews(), runs=runs, faults=Faults(ignore_recorded=kw.get("rerun", False))
    )
    if kw.get("kill"):
        ports.hooks = KillAfter(kw["kill"])
    return compile_definition(definition(start), default_registry(), ports=ports, journal=journal, checkpointer=saver)


async def out_of(g: Any, run: str) -> dict[str, Any]:
    return (await g.aget_state(config(run))).values[channel("open")]


async def test_one_child_starts_with_the_mapped_input_when_no_list_is_set() -> None:
    runs = FakeRuns()
    g = build({"workflow": "case", "input": {"letter": "$.input.letter"}}, runs, MemoryJournal(), InMemorySaver())
    await g.ainvoke({"input": PERSONS}, config("p1"), durability="sync")
    env = await out_of(g, "p1")
    assert env["port"] == "started" and env["out"]["count"] == 1
    assert [c["input"] for c in runs.started.values()] == [{"letter": "L-1"}]


async def test_one_child_starts_per_item_in_order_with_item_and_index_mapped() -> None:
    runs = FakeRuns()
    g = build(PER_PERSON, runs, MemoryJournal(), InMemorySaver())
    await g.ainvoke({"input": PERSONS}, config("p2"), durability="sync")
    env = await out_of(g, "p2")
    assert [r["runId"] for r in env["out"]["runs"]] == ["child0", "child1", "child2"]
    assert [c["input"] for c in runs.started.values()] == [
        {"name": "Ana", "position": 0, "letter": "L-1"},
        {"name": "Bo", "position": 1, "letter": "L-1"},
        {"name": "Cy", "position": 2, "letter": "L-1"},
    ]


async def test_an_empty_list_starts_nothing_and_takes_started() -> None:
    runs = FakeRuns()
    g = build(PER_PERSON, runs, MemoryJournal(), InMemorySaver())
    await g.ainvoke({"input": {"persons": []}}, config("p3"), durability="sync")
    assert (await out_of(g, "p3"))["out"]["count"] == 0 and runs.calls == 0


async def test_a_step_run_again_after_a_crash_starts_no_second_child() -> None:
    """The kill lands after the step's row is finished, and the re-run ignores the recorded output, so the step runs
    a second time on a new attempt. Its children are keyed by run, step, iteration and item, not by attempt."""
    runs, journal, saver = FakeRuns(), MemoryJournal(), InMemorySaver()
    with pytest.raises(Killed):
        await build(PER_PERSON, runs, journal, saver, kill="open").ainvoke(
            {"input": PERSONS}, config("p4"), durability="sync"
        )
    g = build(PER_PERSON, runs, journal, saver, rerun=True)
    await g.ainvoke(None, config("p4"), durability="sync")
    assert runs.calls == 6 and len(runs.started) == 3
    assert [r["created"] for r in (await out_of(g, "p4"))["out"]["runs"]] == [False, False, False]


async def test_a_start_that_raises_is_retried_not_reconciled_through_the_tool_gateway() -> None:
    runs = FakeRuns(fail=1)
    g = build(PER_PERSON, runs, MemoryJournal(), InMemorySaver())
    await g.ainvoke({"input": PERSONS}, config("p5"), durability="sync")
    env = await out_of(g, "p5")
    assert env["port"] == "started" and len(runs.started) == 3


async def test_a_refused_item_takes_the_error_port_with_the_children_already_started() -> None:
    runs = FakeRuns(refuse_at=1)
    g = build(PER_PERSON, runs, MemoryJournal(), InMemorySaver())
    await g.ainvoke({"input": PERSONS}, config("p6"), durability="sync")
    env = await out_of(g, "p6")
    assert env["port"] == "error" and env["out"]["code"] == "workflow_paused"
    assert [r["index"] for r in env["out"]["runs"]] == [0] and len(runs.started) == 1


async def test_a_value_that_is_not_a_list_or_too_long_starts_nothing() -> None:
    for run, payload, start, code in (
        ("p7", {"persons": {"name": "Ana"}}, PER_PERSON, "not_a_list"),
        ("p8", {"persons": None}, PER_PERSON, "not_a_list"),
        ("p9", PERSONS, PER_PERSON | {"maxItems": 2}, "too_many_items"),
    ):
        runs = FakeRuns()
        g = build(start, runs, MemoryJournal(), InMemorySaver())
        await g.ainvoke({"input": payload}, config(run), durability="sync")
        env = await out_of(g, run)
        assert (env["port"], env["out"]["code"], runs.calls) == ("error", code, 0)


def test_item_paths_pass_in_a_loop_input_and_are_refused_anywhere_else() -> None:
    assert validate(definition(PER_PERSON), default_registry()) == []
    no_loop = {"workflow": "case", "input": {"name": "$.item.name"}}
    checks = validate(definition(no_loop), default_registry())
    assert [(c["node"], c["code"]) for c in checks] == [("open", "item_outside_loop")]
