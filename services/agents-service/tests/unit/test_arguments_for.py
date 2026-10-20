"""Graph tool calls name inputs the graph's way; an imported operation spells them its own way (c-057)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.tool_directory import OperationRef
from ops_agents.graphs.common import GraphDeps
from ops_agents.graphs.definition import arguments_for
from tests.conftest import SEED, FakeGraphModels


class Directory:
    def __init__(self, ops: list[OperationRef]) -> None:
        self.ops = ops

    async def operations(self) -> list[OperationRef]:
        return self.ops


def ref(name: str, props: dict[str, Any]) -> OperationRef:
    return OperationRef(name, "", "read", {"type": "object", "properties": props}, False, None, "Bank")


async def test_values_are_renamed_to_the_operations_inputs() -> None:
    deps = GraphDeps(load_catalog(SEED), None, FakeGraphModels(), None, "default")  # type: ignore[arg-type]
    deps = replace(
        deps,
        tools=Directory(
            [
                ref("get_customer", {"customer_id": {}}),
                ref("place_hold", {"account_id": {}, "amount": {}, "reason": {}}),
            ]
        ),
    )
    assert await arguments_for(deps, "get_customer", {"customerId": "CUS-1"}) == {"customer_id": "CUS-1"}
    assert await arguments_for(deps, "place_hold", {"accountId": "A", "amount": 1.0, "reason": "r"}) == {
        "account_id": "A",
        "amount": 1.0,
        "reason": "r",
    }
    # A fixture tool spelled the graph's way, and a tool the directory does not know, keep their names.
    deps = replace(deps, tools=Directory([ref("get_customer", {"customerId": {}})]))
    assert await arguments_for(deps, "get_customer", {"customerId": "CUS-1"}) == {"customerId": "CUS-1"}
    assert await arguments_for(deps, "unknown_tool", {"customerId": "CUS-1"}) == {"customerId": "CUS-1"}
