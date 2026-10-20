"""A paused step's calls in a reviewer's words (c-289), by failure mode: a tool name, a raw key or a raw float in the
question; a reviewer card template left unfilled because the call spells its keys differently; an options step
asking about one option only; and the decision's document not found when the workflow nests its file id."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ops_agents.api.review_text import describe_call, question, source_file

HOLD = {"tool": "place_hold", "input": {"account_id": "CHQ-2219", "amount": 3250.0, "reason": "NS-2026-GN-01187"}}
SCHEMA = {"properties": {"accountId": {"type": "string"}, "amount": {"type": "number"}, "reason": {"type": "string"}}}


class _Ops:
    def __init__(self, ops: list[Any]) -> None:
        self._ops = ops

    async def operations(self) -> list[Any]:
        return self._ops


def _rt(template: Any = None, ops: list[Any] | None = None) -> Any:
    tool = SimpleNamespace(approval=template, input_schema=SCHEMA, description="") if template else None

    def found(_name: str) -> Any:
        return tool

    return SimpleNamespace(catalog=SimpleNamespace(tool=found), directory=lambda: _Ops(ops or []))


@pytest.mark.asyncio
async def test_without_a_card_a_call_is_worded_from_its_schema_with_no_tool_name_key_or_raw_float() -> None:
    op = SimpleNamespace(
        name="place_hold", input_schema={"properties": {"account_id": {"title": "Account"}}}, description=""
    )
    said = await describe_call(_rt(ops=[op]), HOLD, currency="CAD", money_key="amount")
    assert said["sentence"] == "Place hold: account CHQ-2219, amount 3,250.00 CAD, reason NS-2026-GN-01187"
    assert "place_hold" not in said["sentence"] and "3250.0" not in said["sentence"] and "_" not in said["sentence"]


@pytest.mark.asyncio
async def test_a_reviewer_card_fills_from_a_call_that_spells_its_keys_differently() -> None:
    card = SimpleNamespace(
        title="Hold {amount} on account {accountId}",
        action="Hold {amount} on {accountId}",
        consequence="The customer cannot withdraw these funds until the hold is released.",
        fields=[("Account", "{accountId}"), ("Amount", "{amount}")],
    )
    said = await describe_call(_rt(card), HOLD, currency="CAD", money_key="amount")
    assert said["sentence"] == "Hold 3,250.00 CAD on account CHQ-2219"
    assert said["fields"] == [{"label": "Account", "value": "CHQ-2219"}, {"label": "Amount", "value": "3,250.00 CAD"}]


@pytest.mark.asyncio
async def test_a_machine_id_is_left_out_and_the_operations_description_says_what_it_does() -> None:
    op = SimpleNamespace(
        name="apply_tool_access", input_schema={}, description="Grants or refuses the access. Internal."
    )
    call = {
        "tool": "apply_tool_access",
        "input": {"moduleId": "mod_core_banking", "approvalId": "apr_f150a1", "decision": "approved"},
    }
    said = await describe_call(_rt(ops=[op]), call, currency=None, money_key=None)
    assert said["fields"] == [{"label": "Decision", "value": "approved"}]
    assert said["consequence"] == "Grants or refuses the access."


def test_a_step_with_options_asks_which_one_for_whom() -> None:
    assert (
        question(options=["Hold", "Flag"], first=None, customer="Marcus Bell", title="Levy notice")
        == "Hold or flag for Marcus Bell?"
    )
    assert (
        question(options=["Approve", "Reject"], first=None, customer="", title="Tool access request")
        == "Tool access request: approve or reject?"
    )
    assert (
        question(options=[], first={"sentence": "Hold 3,250.00 CAD on account CHQ-2219"}, customer="", title="t")
        == "Hold 3,250.00 CAD on account CHQ-2219?"
    )


def test_the_decisions_file_is_found_wherever_the_workflow_nested_it() -> None:
    assert source_file({"record": {"name": "Marcus Bell", "documentFileId": "fil_9a8b7c"}}, None) == "fil_9a8b7c"
    assert source_file({"note": "fil_ is not a file", "id": "case_1"}, {"accountId": "CHQ-2219"}) is None
