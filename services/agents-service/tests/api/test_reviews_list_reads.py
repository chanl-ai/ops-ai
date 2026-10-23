"""The reviews list draws every waiting typed task (c-288) without a query per task (proto-worker's tick 32 count): a
task's type, its assist and the cases its run opened are read once for the list, so a team with five tasks waiting
reads them in as many statements as a team with one."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import event

from ops_agents.api.task_type_seeds import seeded_store
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RunStore
from tests.api.test_case_page import data, typed_case
from tests.api.test_case_routes import started_run
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, TENANT

TABLES = ("task_types", "task_type_versions", "task_assists", "engine_steps", "cases")


async def typed_waiting(s: Stack, case_id: str, n: int) -> None:
    """`n` runs on the case, each waiting on an acknowledgement task, the type that shows the run's cases."""
    c, rt = s
    for i in range(n):
        run = await started_run(c, BUILDER, f"ack{n}_{i}_{case_id[-6:]}")
        assert (
            await c.post(f"/v1/cases/{case_id}/events", json={"kind": "run", "ref": run}, headers=BUILDER)
        ).status_code == 201
        payload = {
            "node": "review",
            "iteration": 1,
            "step_id": f"{run}:review:1",
            "title": "Send the reply?",
            "taskType": {"id": "acknowledgement"},
            "params": {"title": "Send the reply?", "reply": "We have your letter."},
        }
        waiting = {"node": "review", "iteration": 1, "interruptId": f"i{i}", "payload": payload}
        with tenant_scope(TENANT):
            await RunStore(EngineTransactions(rt.db)).update(run, status="waiting", waiting=waiting)


def _reads(statements: list[str]) -> dict[str, int]:
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    return {t: sum(f"FROM {t} " in f"{s} " or f"FROM {t}\n" in s for s in selects) for t in TABLES}


async def test_typed_tasks_on_the_reviews_list_read_their_types_assists_and_cases_once(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    with tenant_scope(TENANT):
        await seeded_store(rt.db, "team_ops")  # once per process and team, before any list is counted
    counts: list[dict[str, int]] = []
    for n in (1, 5):
        await typed_waiting(stack, await typed_case(stack, customer=f"C-ack{n}"), n)
        seen: list[str] = []

        def record(_conn: Any, _cursor: Any, statement: str, *_: Any, into: list[str] = seen) -> None:
            into.append(statement)

        event.listen(rt.db.sync_engine, "before_cursor_execute", record)
        listed = data(await c.get("/reviews", params={"view": "open", "pageSize": 100}, headers=BUILDER))["data"]
        event.remove(rt.db.sync_engine, "before_cursor_execute", record)
        rows = cast(list[dict[str, Any]], listed)
        typed = [
            r for r in rows if cast(dict[str, Any], r.get("task") or {}).get("type", {}).get("id") == "acknowledgement"
        ]
        assert len(typed) >= n and all(r["task"]["regions"] for r in typed), [r.get("title") for r in rows]
        counts.append(_reads(seen))
    assert counts[0] == counts[1], counts


async def old_waiting(s: Stack, tag: str, n: int) -> None:
    """`n` runs waiting on a review older than typed steps, of a workflow whose live version now names a type, which
    draws through that type with the step's params resolved against each run's steps (legacy_tasks)."""
    c, rt = s
    typed = (Path(__file__).parents[1] / "fixtures" / "engine" / "basic.yaml").read_text()
    typed = typed.replace(
        'parameters: {title: Refund over 100, summary: "$.nodes.lookup.out"}',
        "parameters: {title: Refund over 100, taskType: {id: generic_decision},"
        ' params: {title: "Refund for {$.input.customerId}?"}}',
    )
    for i in range(n):
        workflow = f"old{n}_{i}_{tag}"
        assert "taskType" in typed
        created = await c.post(
            "/v1/workflows/definitions",
            json={"yaml": typed.replace("id: refund_check", f"id: {workflow}", 1)},
            headers=BUILDER,
        )
        assert created.status_code == 201, created.text
        published = await c.post(f"/v1/workflows/definitions/{workflow}/publish-requests", json={}, headers=BUILDER)
        assert published.status_code == 201, published.text
        r = await c.post(
            "/v1/runs", json={"workflowId": workflow, "input": {"customerId": "C-1", "amount": 1}}, headers=BUILDER
        )
        run = str(r.json()["data"]["runId"])
        payload = {"node": "review", "iteration": 1, "step_id": f"{run}:review:1", "title": "Refund over 100"}
        waiting = {"node": "review", "iteration": 1, "interruptId": f"o{i}", "payload": payload}
        with tenant_scope(TENANT):
            await RunStore(EngineTransactions(rt.db)).update(run, status="waiting", waiting=waiting)


async def test_old_reviews_on_the_reviews_list_read_their_runs_steps_once(stack: Stack) -> None:  # noqa: F811
    """Tick 34: legacy_tasks read a run's steps for each old review on the list (legacy_tasks.py:71)."""
    c, rt = stack
    with tenant_scope(TENANT):
        await seeded_store(rt.db, "team_ops")
    counts: list[dict[str, int]] = []
    for n in (1, 5):
        await old_waiting(stack, uuid4().hex[:6], n)
        seen: list[str] = []

        def record(_conn: Any, _cursor: Any, statement: str, *_: Any, into: list[str] = seen) -> None:
            into.append(statement)

        event.listen(rt.db.sync_engine, "before_cursor_execute", record)
        listed = data(await c.get("/reviews", params={"view": "open", "pageSize": 100}, headers=BUILDER))["data"]
        event.remove(rt.db.sync_engine, "before_cursor_execute", record)
        rows = cast(list[dict[str, Any]], listed)
        drawn = [r for r in rows if str(r.get("workflowId", "")).startswith(f"old{n}_")]
        assert len(drawn) == n and all(r["task"]["type"]["id"] == "generic_decision" for r in drawn), drawn
        assert all(r["task"]["regions"][0]["data"]["title"] == "Refund for C-1?" for r in drawn), drawn[0]["task"]
        counts.append(_reads(seen))
    assert counts[0]["engine_steps"] == counts[1]["engine_steps"], counts
