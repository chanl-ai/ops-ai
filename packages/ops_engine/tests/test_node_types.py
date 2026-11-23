"""The registry refuses a second definition of one type version and a type whose form does not match its parameters,
and a review's options become its out ports."""

from __future__ import annotations

import re
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
        parameters: dict[str, Any] = dict(t.parameters)
        ui: dict[str, Any] = dict(t.ui)
        view: dict[str, Any] = t.view()
        props = set(parameters.get("properties") or {})
        assert set(ui["fields"]) == props, t.id
        assert view["ui"]["order"], t.id


def test_a_form_that_misses_or_invents_a_setting_is_refused() -> None:
    end = default_registry().get("ops.flow.end", 1)
    end_fields: dict[str, Any] = cast(dict[str, Any], end.ui["fields"])
    missing = replace(end, ui={"order": ["outcome"], "fields": {"outcome": end_fields["outcome"]}})
    with pytest.raises(ValueError, match="output has no form field"):
        TypeRegistry([missing])
    fields = {**end_fields, "script": {"label": "Script", "widget": "textarea"}}
    invented = replace(end, ui={"order": [*fields], "fields": fields})
    with pytest.raises(ValueError, match="script: not a parameter"):
        TypeRegistry([invented])
    loader = replace(
        end,
        ui={
            "order": ["outcome", "output"],
            "fields": {**end_fields, "outcome": {"label": "O", "widget": "source", "source": "http"}},
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


_NOT_FOR_BUILDERS = re.compile(r"ops\.|`|\$\.|Effects:|-service|gateway|\bports?\b", re.IGNORECASE)


def test_every_type_explains_itself_to_a_builder_in_plain_words() -> None:
    """The step sheet shows summary and how to people who build workflows; type ids, paths, port names and service
    names there read as code."""
    problems: list[str] = []
    for t in default_registry().all():
        if not t.summary.strip() or not t.how.strip():
            problems.append(f"{t.id}: summary or how is empty")
            continue
        if len(t.summary) > 120 or not t.summary.endswith(".") or len(re.findall(r"[.!?](?:\s|$)", t.summary)) != 1:
            problems.append(f"{t.id}: summary is not one sentence under 120 characters")
        for name, text in (("summary", t.summary), ("how", t.how)):
            if found := _NOT_FOR_BUILDERS.search(text):
                problems.append(f"{t.id}: {name} contains {found.group(0)!r}")
    assert not problems, "\n".join(problems)
