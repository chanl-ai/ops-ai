"""The Join (c-278) on an in-memory checkpointer and journal, by failure mode: the step after a fork runs once per
arriving branch; a Join waits for ever on a branch an If sent elsewhere; a Join reached by one branch, or two
branches meeting at a step that cannot wait, saves without a word; a crash between a branch and the Join replays a
branch's call or runs the Join twice; a Join goes on while a branch still waits on a person."""

from __future__ import annotations

import contextlib
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ops_engine import default_registry
from ops_engine.compiler import channel, compile_definition
from ops_engine.definition import advise, parse, validate
from ops_engine.journal import MemoryJournal
from ops_engine.ports import EnginePorts
from tests.test_compiler import FakeReviews, FakeTools, KillAfter, Killed, config


def node(nid: str, kind: str, **params: Any) -> dict[str, Any]:
    return {"id": nid, "type": kind, "typeVersion": 1, "name": nid, "parameters": params}


def wire(source: str, port: str, target: str) -> dict[str, Any]:
    return {"from": {"node": source, "port": port}, "to": {"node": target, "port": "in"}}


def forked(meet: str = "ops.flow.join", *, review_c: bool = False) -> dict[str, Any]:
    """start → a, which forks to b and to an If; the If's true way goes c → e (or a review) to `j`, its false way
    ends; b goes straight to `j`. So the branch through c reaches `j` a step later than b, or never."""
    c_branch = (
        node("e", "ops.flow.humanReview", title="Check") if review_c else node("e", "ops.data.set", values={"e": 2})
    )
    e_port = "approve" if review_c else "out"
    nodes = [
        node("start", "ops.trigger.request"),
        node("a", "ops.data.set", values={"a": 1}),
        node("b", "ops.action.tool", operation="get_customer", input={"customer_id": "C-1"}),
        node("go", "ops.flow.if", conditions=[{"left": "$.input.route", "op": "eq", "right": True}]),
        node("c", "ops.data.set", values={"c": 1}),
        c_branch,
        node("j", meet, **({} if meet == "ops.flow.join" else {"values": {"j": 1}})),
        node("after", "ops.data.set", values={"joined": "$.nodes.j.out"}),
        node("done", "ops.flow.end", outcome="done"),
        node("away", "ops.flow.end", outcome="away"),
        node("failed", "ops.flow.end", outcome="failed"),
    ]
    wires = [
        wire("start", "payload", "a"),
        wire("a", "out", "b"),
        wire("a", "out", "go"),
        wire("go", "true", "c"),
        wire("go", "false", "away"),
        wire("c", "out", "e"),
        wire("e", e_port, "j"),
        wire("b", "ok", "j"),
        wire("b", "refused", "failed"),
        wire("b", "error", "failed"),
        wire("j", "out", "after"),
        wire("after", "out", "done"),
    ]
    if review_c:
        wires.append(wire("e", "reject", "failed"))
    return {"schemaVersion": 2, "id": "fork", "name": "Fork", "nodes": nodes, "connections": wires}


def build(
    d: dict[str, Any], tools: FakeTools, journal: MemoryJournal, saver: InMemorySaver, kill: str | None = None
) -> Any:
    ports = EnginePorts(tools=tools, reviews=FakeReviews())
    if kill:
        ports.hooks = KillAfter(kill)
    definition = parse(d)
    return compile_definition(definition, default_registry(), ports=ports, journal=journal, checkpointer=saver)


def ran(journal: MemoryJournal, node_id: str) -> int:
    return sum(1 for r in journal.rows.values() if r.node_id == node_id and r.status == "ok")


async def test_the_step_after_a_join_runs_once_with_each_branch_by_the_step_it_came_from() -> None:
    d = forked()
    assert validate(parse(d), default_registry()) == []
    tools, journal, saver = FakeTools(), MemoryJournal(), InMemorySaver()
    g = build(d, tools, journal, saver)
    await g.ainvoke({"input": {"route": True}}, config("j1"), durability="sync")
    values = (await g.aget_state(config("j1"))).values
    assert (ran(journal, "j"), ran(journal, "after")) == (1, 1), journal.rows
    assert values[channel("after")]["out"]["joined"] == {"b": {"id": "C-1", "name": "Ana"}, "e": {"e": 2}}


async def test_without_a_join_the_shared_step_runs_once_per_branch_and_validate_says_so() -> None:
    """Today's behaviour, pinned so the warning stays true: a plain step where two branches of one fork meet."""
    d = forked(meet="ops.data.set")
    definition = parse(d)
    assert [(w["node"], w["code"], w["level"]) for w in advise(definition, default_registry())] == [
        ("j", "fork_without_join", "warning")
    ]
    tools, journal, saver = FakeTools(), MemoryJournal(), InMemorySaver()
    await build(d, tools, journal, saver).ainvoke({"input": {"route": True}}, config("j2"), durability="sync")
    assert ran(journal, "after") == 2
    assert advise(parse(forked()), default_registry()) == []


async def test_a_branch_an_if_sent_elsewhere_is_null_and_the_join_runs_once() -> None:
    tools, journal, saver = FakeTools(), MemoryJournal(), InMemorySaver()
    g = build(forked(), tools, journal, saver)
    await g.ainvoke({"input": {"route": False}}, config("j3"), durability="sync")
    values = (await g.aget_state(config("j3"))).values
    assert ran(journal, "j") == 1 and values[channel("after")]["out"]["joined"] == {
        "b": {"id": "C-1", "name": "Ana"},
        "e": None,
    }
    assert values[channel("away")]["out"]["outcome"] == "away"


def test_a_join_reached_by_one_branch_is_refused_by_validate() -> None:
    d = forked()
    d["connections"] = [c for c in d["connections"] if not (c["from"]["node"] == "b" and c["to"]["node"] == "j")]
    d["connections"].append(wire("b", "ok", "after"))
    checks = validate(parse(d), default_registry())
    assert [(c["node"], c["code"]) for c in checks] == [("j", "join_needs_branches")], checks


async def test_a_crash_after_a_branch_replays_no_call_and_runs_the_join_once() -> None:
    tools, journal, saver = FakeTools(), MemoryJournal(), InMemorySaver()
    with contextlib.suppress(Killed):
        await build(forked(), tools, journal, saver, kill="b").ainvoke(
            {"input": {"route": True}}, config("j4"), durability="sync"
        )
    g = build(forked(), tools, journal, saver)
    await g.ainvoke(None, config("j4"), durability="sync")
    assert (len(tools.calls), ran(journal, "j"), ran(journal, "after")) == (1, 1, 1), (tools.calls, journal.rows)


async def test_a_branch_waiting_on_a_person_holds_the_join_until_it_is_decided() -> None:
    tools, journal, saver = FakeTools(), MemoryJournal(), InMemorySaver()
    g = build(forked(review_c=True), tools, journal, saver)
    await g.ainvoke({"input": {"route": True}}, config("j5"), durability="sync")
    state = await g.aget_state(config("j5"))
    assert state.interrupts and state.values.get(channel("j")) is None, state.values.get(channel("j"))
    await g.ainvoke(Command(resume={"decision": "approved", "by": "m"}), config("j5"), durability="sync")
    values = (await g.aget_state(config("j5"))).values
    assert ran(journal, "j") == 1 and set(values[channel("after")]["out"]["joined"]) == {"b", "e"}
