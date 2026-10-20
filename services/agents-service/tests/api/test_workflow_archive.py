"""Archiving a workflow (c-274), by failure mode: an archived workflow still starts runs (live, test or as a child), a
trigger still serves it, it stays on the lists, someone who may not delete it archives it, or restoring loses what it
was."""

from __future__ import annotations

from typing import Any

import pytest

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import DefinitionStore, NotLiveError, RunStore
from tests.api.test_case_routes import started_run
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, TENANT, VIEWER


def data(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


def listed(page: dict[str, Any], key: str = "workflowId") -> dict[str, str]:
    return {str(w[key]): str(w["status"]) for w in page["data"]}


async def test_an_archived_workflow_starts_no_run_leaves_the_lists_and_restores_as_it_was(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    run = await started_run(c, BUILDER, "fee_check")
    assert (await c.post("/v1/workflows/definitions/fee_check/archive", headers=VIEWER)).status_code == 403
    archived = data(await c.post("/v1/workflows/definitions/fee_check/archive", headers=BUILDER))
    assert archived["archivedAt"] and archived["liveVersion"] == 1, archived
    for mode in ("live", "test"):
        body = {"workflowId": "fee_check", "mode": mode, "input": {"customerId": "C-1", "amount": 1}}
        refused = await c.post("/v1/runs", json=body, headers=BUILDER)
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "workflow_archived", (
            mode,
            refused.text,
        )
    assert data(await c.get(f"/v1/runs/{run}", headers=BUILDER))["id"] == run, "its runs are kept"
    defs = data(await c.get("/v1/workflows/definitions", headers=BUILDER))
    assert "fee_check" not in listed(defs) and defs["facets"]["status"].get("archived") == 1, defs["facets"]
    shown = data(await c.get("/v1/workflows/definitions?status=archived", headers=BUILDER))
    assert listed(shown) == {"fee_check": "archived"}
    merged = data(await c.get("/v1/workflows", headers=BUILDER))
    assert "fee_check" not in listed(merged, "id") and merged["facets"]["status"].get("archived") == 1
    restored = data(await c.post("/v1/workflows/definitions/fee_check/restore", headers=BUILDER))
    assert restored["archivedAt"] is None and restored["liveVersion"] == 1 and not restored["paused"], restored
    again = await c.post(
        "/v1/runs", json={"workflowId": "fee_check", "input": {"customerId": "C-1", "amount": 1}}, headers=BUILDER
    )
    assert again.status_code == 202, again.text


async def test_a_child_start_and_the_mailbox_listener_leave_an_archived_workflow_alone(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    run = await started_run(c, BUILDER, "child_check")
    data(await c.post("/v1/workflows/definitions/child_check/archive", headers=BUILDER))
    tx = EngineTransactions(rt.db)
    with tenant_scope(TENANT):
        stored = await DefinitionStore(tx).get("child_check")
        assert stored is not None
        child: dict[str, Any] = {
            "id": "wfrun_child_archived",
            "team_id": "team_ops",
            "workflow_id": "child_check",
            "version": stored["version"],
            "digest": stored["digest"],
            "run_key": "child:archived",
            "mode": "test",
            "input": {},
            "created_by": f"run:{run}",
        }
        with pytest.raises(NotLiveError) as refused:
            await RunStore(tx).create(child)
    assert refused.value.stage == "archived"
    assert "child_check" not in {d["workflow_id"] for d in await DefinitionStore(tx).live_everywhere()}
