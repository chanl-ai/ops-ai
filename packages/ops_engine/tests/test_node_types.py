"""The registry refuses a second definition of one type version and a type whose form does not match its parameters,
and a review's options become its out ports."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

from ops_engine import TypeRegistry, default_registry
from ops_engine.node_types import BASIC_TYPES


def test_a_type_version_registers_once() -> None:
    reg = default_registry()
    with pytest.raises(ValueError, match="already registered"):
        reg.register(BASIC_TYPES[0])


def test_review_options_are_its_out_ports() -> None:
    review = default_registry().get("ops.flow.humanReview", 1)
    assert review.output_ports({}) == ["approve", "reject"]
    assert review.output_ports({"options": ["hold", {"name": "flag", "label": "Flag it"}]}) == ["hold", "flag"]


def test_every_built_type_has_a_form_for_each_of_its_parameters() -> None:
    for t in default_registry().all():
        props = set(t.parameters.get("properties") or {})
        assert set(t.ui["fields"]) == props, t.id
        assert t.view()["ui"]["order"], t.id


def test_a_form_that_misses_or_invents_a_setting_is_refused() -> None:
    end = default_registry().get("ops.flow.end", 1)
    missing = replace(end, ui={"order": ["outcome"], "fields": {"outcome": end.ui["fields"]["outcome"]}})
    with pytest.raises(ValueError, match="output has no form field"):
        TypeRegistry([missing])
    fields = {**end.ui["fields"], "script": {"label": "Script", "widget": "textarea"}}
    invented = replace(end, ui={"order": [*fields], "fields": fields})
    with pytest.raises(ValueError, match="script: not a parameter"):
        TypeRegistry([invented])
    loader = replace(
        end,
        ui={
            "order": ["outcome", "output"],
            "fields": {**end.ui["fields"], "outcome": {"label": "O", "widget": "source", "source": "http"}},
        },
    )
    with pytest.raises(ValueError, match="unknown option source 'http'"):
        TypeRegistry([loader])


@pytest.mark.parametrize(
    ("type_id", "field", "params"),
    [
        ("ops.action.tool", "operation", {"operation": "$.input.op"}),
        ("ops.action.tool", "approvedBy", {"operation": "get_customer", "approvedBy": "$.input.who"}),
        ("ops.ai.agent", "agent", {"agent": "$.input.agent"}),
        ("ops.flow.humanReview", "approves", {"approves": "$.nodes.x.out"}),
    ],
)
def test_what_a_step_acts_on_cannot_be_read_from_the_run(type_id: str, field: str, params: dict[str, object]) -> None:
    """A path in an identity field would let run input choose the operation, agent or approver a reviewer approved."""
    t = default_registry().get(type_id, 1)
    errors = list(cast(Any, Draft202012Validator(dict(t.parameters))).iter_errors(params))
    assert [list(e.path) for e in errors] == [[field]], errors
    literal = {k: ("get_customer" if k == "operation" else "review") for k in params}
    assert not list(cast(Any, Draft202012Validator(dict(t.parameters))).iter_errors(literal))
