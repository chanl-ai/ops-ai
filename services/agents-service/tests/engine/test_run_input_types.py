"""A required input left out is refused on every start path, on the real database. `start_run` is the call a
person's start, a hosted form, a batch row, an agent's tool call, an email and a service event all make, and a Start
workflow step reaches it through `WorkflowStarts`; packages/ops_engine/tests/test_run_entry.py fails when a path
writes a run any other way."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from ops_agents.api.engine_runs import start_run
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.ports import RunRefusedError
from ops_service_kit.errors import Unprocessable
from tests.engine.test_start_workflow import TEAM, Tenant, tenants  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_worker import engine  # noqa: F401  # pyright: ignore[reportUnusedImport]

CASE = parse(
    {
        "schemaVersion": 2,
        "id": "case",
        "name": "Case",
        "nodes": [
            {
                "id": "in",
                "type": "ops.trigger.request",
                "typeVersion": 1,
                "name": "Request",
                "parameters": {
                    "inputSchema": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {"name": {"type": "string", "title": "Name"}},
                    }
                },
            },
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {"outcome": "open"}},
        ],
        "connections": [{"from": {"node": "in", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }
)


@pytest.mark.parametrize("path", ["start_run", "start_workflow_step"])
async def test_a_required_input_left_out_starts_no_run(path: str, tenants: Callable[[], Tenant]) -> None:  # noqa: F811
    t = tenants()
    stored = await t.publish(CASE)
    parent = await t.parent()
    with tenant_scope(t.id):
        if path == "start_run":
            with pytest.raises(Unprocessable) as refused:
                await start_run(
                    t.runs, stored, team_id=TEAM, mode="live", input={"name": " "}, run_key=None, created_by="b@x"
                )
            assert refused.value.code == "invalid_input" and (refused.value.details or {}).get("path") == "name"
        else:
            with pytest.raises(RunRefusedError) as stopped:
                await t.starts.start(parent, "case", {}, "k:open:1:0")
            assert stopped.value.code == "invalid_input" and "Name" in str(stopped.value)
    assert await t.children() == []


async def test_a_stored_schema_that_is_not_json_schema_starts_no_run_and_says_so(tenants: Callable[[], Tenant]) -> None:  # noqa: F811
    """A version saved before the save check: `required: true` must answer `input_schema_invalid`, not fail on the
    schema's own shape while reading required fields."""
    t = tenants()
    wire = CASE.wire()
    wire["nodes"][0]["parameters"]["inputSchema"]["required"] = True
    stored = await t.publish(parse(wire))
    with tenant_scope(t.id), pytest.raises(Unprocessable) as refused:
        await start_run(
            t.runs, stored, team_id=TEAM, mode="live", input={"name": "Ana"}, run_key=None, created_by="b@x"
        )
    assert refused.value.code == "input_schema_invalid", refused.value
    assert await t.children() == []
