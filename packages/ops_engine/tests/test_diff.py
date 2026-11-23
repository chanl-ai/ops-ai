"""The diff between two definitions, by failure mode: a changed setting is left out of a step's changes."""

from __future__ import annotations

import copy
from typing import Any

from ops_engine.diff import diff

BEFORE: dict[str, Any] = {
    "id": "refund",
    "name": "Refund",
    "nodes": [
        {
            "id": "start",
            "type": "ops.trigger.request",
            "typeVersion": 1,
            "name": "Request",
            "position": {"x": 0, "y": 0},
        },
        {
            "id": "ask",
            "type": "ops.ai.agent",
            "typeVersion": 1,
            "name": "Check the refund",
            "parameters": {"agent": "refund-checker", "prompt": "Check the amount.", "maxToolCalls": 4},
            "position": {"x": 300, "y": 0},
        },
        {"id": "end", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "position": {"x": 600, "y": 0}},
    ],
    "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "ask", "port": "in"}}],
}


def test_every_changed_setting_of_a_step_is_listed_and_a_move_is_not_a_change() -> None:
    after = copy.deepcopy(BEFORE)
    ask: dict[str, Any] = after["nodes"][1]
    ask["name"] = "Check the refund twice"
    ask["onError"] = "continue"
    ask["parameters"]["prompt"] = "Check the amount and the customer."
    del ask["parameters"]["maxToolCalls"]
    after["nodes"][2]["position"] = {"x": 700, "y": 80}
    after["nodes"].append({"id": "note", "type": "ops.data.set", "typeVersion": 1, "name": "Note"})
    got = diff(BEFORE, after)
    (step,) = got["changed"]
    fields = {f["field"]: (f["before"], f["after"]) for f in step["fields"]}
    assert fields == {
        "name": ("Check the refund", "Check the refund twice"),
        "onError": (None, "continue"),
        "parameters.prompt": ("Check the amount.", "Check the amount and the customer."),
        "parameters.maxToolCalls": (4, None),
    }
    assert [s["id"] for s in got["moved"]] == ["end"]
    assert [s["id"] for s in got["added"]] == ["note"] and not got["removed"]
