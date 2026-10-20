"""The Calculate step (ops.data.compute) through the compiled graph, by failure mode: run data pasted into a formula
(so the input could write the code the sandbox runs), a path in a formula accepted on save, values left unresolved,
and a failed formula ending the run instead of taking the error port."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from ops_engine import default_registry
from ops_engine.compiler import channel, compile_definition
from ops_engine.definition import parse, validate
from ops_engine.journal import MemoryJournal
from ops_engine.ports import EnginePorts

LEVY = {"levy": {"amount": 3250.0, "served": "2026-10-16", "note": "levy.__class__"}, "balance": 1800}


class FakeExpressions:
    def __init__(self, answer: tuple[dict[str, Any] | None, str | None] = ({"amount": 1800}, None)) -> None:
        self.answer = answer
        self.calls: list[tuple[dict[str, str], dict[str, Any]]] = []

    async def evaluate(
        self, expressions: dict[str, str], values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        self.calls.append((expressions, values))
        return self.answer


def definition(expressions: dict[str, str]) -> Any:
    return parse(
        {
            "schemaVersion": 2,
            "id": "calc",
            "name": "Calculate",
            "nodes": [
                {"id": "start", "type": "ops.trigger.request", "typeVersion": 1},
                {
                    "id": "calc",
                    "type": "ops.data.compute",
                    "typeVersion": 1,
                    "parameters": {
                        "values": {"levy": "$.input.levy", "balance": "$.input.balance"},
                        "expressions": expressions,
                    },
                },
                {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "done"}},
                {"id": "failed", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "failed"}},
            ],
            "connections": [
                {"from": {"node": "start", "port": "payload"}, "to": {"node": "calc", "port": "in"}},
                {"from": {"node": "calc", "port": "out"}, "to": {"node": "done", "port": "in"}},
                {"from": {"node": "calc", "port": "error"}, "to": {"node": "failed", "port": "in"}},
            ],
        }
    )


async def run(expressions: dict[str, str], port: FakeExpressions) -> dict[str, Any]:
    ports = EnginePorts(tools=None, reviews=None, expressions=port)  # type: ignore[arg-type]
    g = compile_definition(
        definition(expressions), default_registry(), ports=ports, journal=MemoryJournal(), checkpointer=InMemorySaver()
    )
    cfg = {"configurable": {"thread_id": "r1", "run_id": "r1", "lease_generation": 1}}
    await g.ainvoke({"input": LEVY}, cfg, durability="sync")
    return dict((await g.aget_state(cfg)).values)


async def test_values_are_resolved_and_the_result_is_the_out_port() -> None:
    port = FakeExpressions()
    values = await run({"amount": "min(levy.amount, balance)"}, port)
    assert port.calls == [({"amount": "min(levy.amount, balance)"}, LEVY)]
    assert values[channel("calc")]["out"] == {"amount": 1800}
    assert values[channel("done")]["out"]["outcome"] == "done"


async def test_run_data_never_becomes_part_of_a_formula() -> None:
    # Saved past the check (an older definition, or one written straight to the store), a path in braces is still
    # sent as written: the input's text "levy.__class__" is never pasted into the code.
    port = FakeExpressions()
    await run({"amount": "{$.input.levy.note} + 1"}, port)
    assert port.calls[0][0] == {"amount": "{$.input.levy.note} + 1"}


def test_a_path_in_a_formula_is_refused_on_save() -> None:
    for formula in ("$.input.balance * 2", "{$.input.levy.note} + 1"):
        found = {(c["code"], c["field"]) for c in validate(definition({"amount": formula}), default_registry())}
        assert ("invalid_parameter", "expressions") in found, (formula, found)
    assert validate(definition({"amount": "min(levy.amount, balance)"}), default_registry()) == []


async def test_a_failed_formula_takes_the_error_port() -> None:
    port = FakeExpressions((None, "amount: UndefinedError: 'missing' is undefined"))
    values = await run({"amount": "missing + 1"}, port)
    assert values[channel("calc")]["port"] == "error"
    assert values[channel("calc")]["out"] == {
        "error": "amount: UndefinedError: 'missing' is undefined",
        "code": "formula_failed",
    }
    assert values[channel("failed")]["out"]["outcome"] == "failed"
