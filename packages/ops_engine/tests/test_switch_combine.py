"""Switch and Combine facts (c-259), by failure mode: a run leaves on a later way when an earlier one held, or on no
way at all; a Switch wired from a way it does not name, or naming one twice, passes its checks; Combine picks a value
silently when sources disagree, calls an empty value a disagreement, or calls 1200 and 1,200.00 (or the same name in
another case) different; a field's precedence is ignored."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ops_engine.compiler import NodeCall, data_combine, flow_switch
from ops_engine.definition import NodeInstance, parse, validate
from ops_engine.node_types import default_registry
from ops_engine.ports import EnginePorts


def call(type_id: str, params: dict[str, Any]) -> NodeCall:
    node = NodeInstance.model_validate({"id": "n", "type": type_id, "typeVersion": 1})
    return NodeCall(
        run_id="run_1",
        node=node,
        type=default_registry().get(type_id, 1),
        iteration=1,
        attempt=1,
        key="run_1:n:1:1",
        params=params,
        generation=None,
        ports=EnginePorts(tools=None, reviews=None),  # type: ignore[arg-type]
        run_input={},
        scope={},
    )


def ways(attachments: int, body: str) -> dict[str, Any]:
    """What came in, as the email arrives at the Switch after the mappings resolve."""
    return {
        "cases": [
            {"name": "attachments", "conditions": [{"left": attachments, "op": "gt", "right": 0}]},
            {"name": "body_only", "conditions": [{"left": body, "op": "empty"}], "combine": "any"},
            {"name": "body_too", "conditions": [{"left": body, "op": "exists"}]},
        ]
    }


async def test_the_first_way_whose_rules_hold_wins_and_otherwise_takes_the_rest() -> None:
    both = await flow_switch(call("ops.flow.switch", ways(2, "")))
    assert (both.port, both.out) == ("attachments", {"case": "attachments"}), "a later way held as well"
    assert (await flow_switch(call("ops.flow.switch", ways(0, "")))).port == "body_only"
    none = await flow_switch(
        call("ops.flow.switch", {"cases": [{"name": "a", "conditions": [{"left": 1, "op": "eq", "right": 2}]}]})
    )
    assert none.port == "otherwise"


async def test_otherwise_shows_the_value_each_case_read_so_a_run_says_why_none_matched() -> None:
    kinds = {
        "cases": [
            {"name": name, "conditions": [{"left": "levy_notice", "op": "eq", "right": name}]}
            for name in ("restraining_notice", "tax_levy")
        ]
    }
    none = await flow_switch(call("ops.flow.switch", kinds))
    assert none.out == {
        "case": "otherwise",
        "tried": [
            {"case": "restraining_notice", "left": "levy_notice", "op": "eq", "right": "restraining_notice"},
            {"case": "tax_levy", "left": "levy_notice", "op": "eq", "right": "tax_levy"},
        ],
    }


def switch_flow(cases: list[dict[str, Any]], wired: list[str]) -> list[str]:
    nodes: list[dict[str, Any]] = [
        {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
        {"id": "pick", "type": "ops.flow.switch", "typeVersion": 1, "parameters": {"cases": cases}},
        *({"id": f"end_{w}", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": w}} for w in wired),
    ]
    connections = [{"from": {"node": "start", "port": "payload"}, "to": {"node": "pick", "port": "in"}}]
    connections += [{"from": {"node": "pick", "port": w}, "to": {"node": f"end_{w}", "port": "in"}} for w in wired]
    d = parse({"schemaVersion": 2, "id": "switchy", "nodes": nodes, "connections": connections})
    return [str(c["code"]) for c in validate(d, default_registry())]


async def test_a_switch_is_wired_only_from_the_ways_it_names_and_each_once() -> None:
    rule = [{"left": "$.input.n", "op": "gt", "right": 0}]
    assert switch_flow([{"name": "big", "conditions": rule}], ["big", "otherwise"]) == []
    assert switch_flow([{"name": "big", "conditions": rule}], ["big", "small"]) != [], "a way it does not name"
    twice = switch_flow([{"name": "big", "conditions": rule}, {"name": "big", "conditions": rule}], ["big"])
    assert "duplicate_port" in twice, twice
    assert "invalid_parameter" in switch_flow([{"name": "otherwise", "conditions": rule}], ["otherwise"])


async def test_combine_keeps_each_source_and_lists_what_they_disagree_on() -> None:
    attachment = {"name": "Marcus Bell", "amount": "1,200.00", "caseNumber": "NS-2026-1187", "phone": ""}
    email = {"name": "  marcus BELL", "amount": 1200, "caseNumber": "NS-2026-1188", "phone": "902 555 0100"}
    out = (
        await data_combine(
            call(
                "ops.data.combine",
                {
                    "sources": [{"name": "attachment", "values": attachment}, {"name": "email", "values": email}],
                    "fields": [
                        {"field": "phone", "from": ["email", "attachment"]},
                        {"field": "amount", "type": "money"},
                    ],
                },
            )
        )
    ).out
    assert out["values"] == {
        "name": "Marcus Bell",
        "amount": "1,200.00",
        "caseNumber": "NS-2026-1187",
        "phone": "902 555 0100",
    }
    assert out["sources"] == {
        "name": "attachment",
        "amount": "attachment",
        "caseNumber": "attachment",
        "phone": "email",
    }
    assert out["hasConflicts"] is True and [c["field"] for c in out["conflicts"]] == ["caseNumber"], out["conflicts"]
    assert out["conflicts"][0]["values"] == [
        {"source": "attachment", "value": "NS-2026-1187"},
        {"source": "email", "value": "NS-2026-1188"},
    ]


async def test_combine_reads_extracted_fields_by_their_value() -> None:
    read = {"amount": {"value": "250", "type": "money", "confidence": 0.9}}
    typed = {"amount": 250.0}
    out = (
        await data_combine(
            call(
                "ops.data.combine", {"sources": [{"name": "read", "values": read}, {"name": "typed", "values": typed}]}
            )
        )
    ).out
    assert (out["hasConflicts"], out["values"]["amount"]) == (False, read["amount"])


async def test_combine_compares_digits_as_numbers_only_in_number_and_money_fields() -> None:
    letter = {"caseNumber": "00123", "account": "0042", "amount": "1,200.00", "fee": "35"}
    email = {"caseNumber": "123", "account": 42, "amount": 1200, "fee": {"value": "35.00", "type": "money"}}
    out = (
        await data_combine(
            call(
                "ops.data.combine",
                {
                    "sources": [{"name": "letter", "values": letter}, {"name": "email", "values": email}],
                    "fields": [{"field": "amount", "type": "money"}],
                },
            )
        )
    ).out
    # Case numbers and account ids keep their leading zeros; a money field, or a read money value, is a number.
    assert [c["field"] for c in out["conflicts"]] == ["caseNumber", "account"], out["conflicts"]


async def test_open_case_takes_a_priority_worked_out_earlier_and_refuses_one_it_does_not_know() -> None:
    from ops_engine.compiler import case_open  # noqa: PLC0415

    opened: list[dict[str, Any]] = []

    class Cases:
        async def open(self, run_id: str, fields: dict[str, Any], key: str) -> Any:
            opened.append(fields)
            return type("Opened", (), {"case_id": "case_1", "created": True})()

    def step(priority: str) -> NodeCall:
        c = call("ops.action.openCase", {"subject": "Complaint", "priority": priority})
        return replace(c, ports=EnginePorts(tools=None, reviews=None, cases=Cases()))  # type: ignore[arg-type]

    assert (await case_open(step("urgent"))).port == "opened" and opened[-1]["priority"] == "urgent"
    refused = await case_open(step("whenever"))
    assert (refused.port, refused.out["code"]) == ("error", "priority_invalid"), refused
    assert validate(parse({**PRIORITY_FLOW}), default_registry()) == [], "a path is a valid priority"


PRIORITY_FLOW: dict[str, Any] = {
    "schemaVersion": 2,
    "id": "triaged",
    "name": "Triaged",
    "nodes": [
        {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "name": "In"},
        {
            "id": "open",
            "type": "ops.action.openCase",
            "typeVersion": 1,
            "name": "Open",
            "parameters": {"subject": "Complaint", "priority": "$.input.priority"},
        },
        {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
    ],
    "connections": [
        {"from": {"node": "in", "port": "payload"}, "to": {"node": "open", "port": "in"}},
        {"from": {"node": "open", "port": "opened"}, "to": {"node": "done", "port": "in"}},
        {"from": {"node": "open", "port": "error"}, "to": {"node": "done", "port": "in"}},
    ],
}
