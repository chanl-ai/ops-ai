"""The Match step (c-210), by failure mode: a name alone opens a case; a street number alone counts as the same
address; a blank field matches a blank field; case or spacing makes the same name differ; a search answer that is not
a list crashes the step."""

from __future__ import annotations

from typing import Any

from ops_engine.compiler import NodeCall, data_match
from ops_engine.definition import NodeInstance
from ops_engine.node_types import default_registry
from ops_engine.ports import EnginePorts

# The levy rule: the name, and the last four of the SSN or the address (six characters at least).
LEVY = {
    "all": [{"left": "name", "op": "equals", "right": "name"}],
    "any": [
        {"left": "ssn_last4", "op": "equals", "right": "ssnLast4"},
        {"left": "address", "op": "overlaps", "right": "address", "minLength": 6},
    ],
}
MARCUS = {"id": "CUS-1", "name": "Marcus Bell", "address": "12 Harbour Street, Halifax NS B3J 1A1", "ssnLast4": "4471"}


def call(item: Any, candidates: Any, rules: dict[str, Any] = LEVY) -> NodeCall:
    node = NodeInstance.model_validate({"id": "match", "type": "ops.data.match", "typeVersion": 1})
    return NodeCall(
        run_id="run_1",
        node=node,
        type=default_registry().get("ops.data.match", 1),
        iteration=1,
        attempt=1,
        key="run_1:match:1:1",
        params={"item": item, "candidates": candidates, **rules},
        generation=None,
        ports=EnginePorts(tools=None, reviews=None),  # type: ignore[arg-type]
        run_input={},
        scope={},
    )


async def test_a_name_alone_is_a_candidate_never_a_match() -> None:
    record = {"name": "Marcus Bell", "address": "9 Other Road, Toronto", "ssn_last4": "0000"}
    out = await data_match(call(record, [MARCUS]))
    assert out.port == "none" and out.out["match"] is None and out.out["candidates"] == [MARCUS]


async def test_the_name_with_the_address_or_the_last_four_matches_despite_case_and_spacing() -> None:
    by_address = {"name": "  marcus   BELL ", "address": "12 harbour street, halifax", "ssn_last4": ""}
    by_ssn = {"name": "Marcus Bell", "address": "", "ssn_last4": "4471"}
    for record in (by_address, by_ssn):
        out = await data_match(call(record, [MARCUS, {"id": "CUS-2", "name": "Ana Silva"}]))
        assert (out.port, out.out["match"]) == ("matched", MARCUS)


async def test_a_street_number_alone_or_a_blank_field_never_matches() -> None:
    short = {"name": "Marcus Bell", "address": "12", "ssn_last4": ""}
    blank = {"name": "Marcus Bell", "address": "", "ssn_last4": ""}
    blank_customer = MARCUS | {"address": "", "ssnLast4": ""}
    assert (await data_match(call(short, [MARCUS]))).port == "none"
    assert (await data_match(call(blank, [blank_customer]))).port == "none"


async def test_a_search_answer_that_is_not_a_list_is_no_candidates() -> None:
    out = await data_match(call({"name": "Marcus Bell"}, None))
    assert (out.port, out.out["candidates"]) == ("none", [])
    single = await data_match(call({"name": "Marcus Bell"}, MARCUS, {"all": LEVY["all"]}))
    assert single.port == "matched"
