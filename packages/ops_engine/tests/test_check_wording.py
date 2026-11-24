"""What a builder reads in a step's Problems: the step's name, never its id or a port name, and the words a form lists
for a choice."""

from __future__ import annotations

from typing import Any

from ops_engine.definition import WorkflowDefinition, validate
from ops_engine.node_types import default_registry


def _definition(nodes: list[dict[str, Any]], connections: list[dict[str, Any]] | None = None) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {"schemaVersion": 2, "id": "wording", "nodes": nodes, "connections": connections or []}
    )


def test_a_dangling_way_out_names_the_step_not_its_id_and_a_choice_names_its_words() -> None:
    d = _definition(
        [
            {"id": "zz01", "type": "ops.trigger.request", "typeVersion": 1, "name": "Refund asked"},
            {
                "id": "zz02",
                "type": "ops.flow.if",
                "typeVersion": 1,
                "parameters": {"conditions": [{"left": 1, "op": "big"}]},
            },
        ],
        [{"from": {"node": "zz01", "port": "payload"}, "to": {"node": "zz02", "port": "in"}}],
    )
    messages = [str(c["message"]) for c in validate(d, default_registry())]
    assert "Nothing follows the True way out of If." in messages
    wrong = [m for m in messages if "must be one of" in m or "accepts" in m]
    assert len(wrong) == 1 and wrong[0].startswith("If: Conditions, row 1, Is must be one of Equal to")
    assert not [m for m in messages if "zz0" in m or " port " in m]
