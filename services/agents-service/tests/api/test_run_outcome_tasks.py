"""Human Tasks lists every task waiting for a person (c-561), by failure mode: a team with more than 200 runs loses the
tasks of its older runs from the list and its count, while those runs still say they wait for a person."""

from __future__ import annotations

from typing import Any, cast

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RunStore
from ops_engine.store.tables import engine_runs
from tests.api.test_case_page import data
from tests.api.test_case_routes import started_run
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, TENANT


async def test_a_task_on_a_run_older_than_the_newest_200_is_listed_and_counted(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    oldest = await started_run(c, BUILDER, "old_task")
    payload = {"node": "review", "iteration": 1, "step_id": f"{oldest}:review:1", "title": "Refund for Zebedee"}
    waiting = {"node": "review", "iteration": 1, "interruptId": "s1", "payload": payload}
    with tenant_scope(TENANT):
        store = RunStore(EngineTransactions(rt.db))
        await store.update(oldest, status="waiting", waiting=waiting)
        first = await store.get(oldest) or {}
    # 200 runs started after it, as a busy mailbox workflow starts them.
    newer: list[dict[str, Any]] = [
        {
            **{k: first[k] for k in ("tenant_id", "team_id", "workflow_id", "version", "digest", "mode", "created_by")},
            "id": f"wfrun_new{i:03d}",
            "run_key": f"new{i:03d}",
            "status": "succeeded",
            "input": {},
            "created_at": f"2099-01-01T00:00:{i % 60:02d}.{i:03d}Z",
            "updated_at": "2099-01-01T00:00:00.000Z",
        }
        for i in range(200)
    ]
    async with rt.db.begin() as conn:
        await conn.execute(engine_runs.insert(), newer)
    found = data(await c.get("/reviews", params={"view": "open", "search": "zebedee"}, headers=BUILDER))
    assert [r["title"] for r in cast(list[dict[str, Any]], found["data"])] == ["Refund for Zebedee"], found
    assert found["viewCounts"]["open"] >= 1
