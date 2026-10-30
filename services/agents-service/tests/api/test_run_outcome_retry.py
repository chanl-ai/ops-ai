"""Retry for a Stuck run (c-561), by failure mode: a Stuck run cannot be moved again, so its only way out is Cancel; a
run that is not Stuck is retried and runs twice; and someone who may not cancel the run retries it."""

from __future__ import annotations

import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_engine.store.tables import ENGINE_BUILD, engine_runs, engine_work
from tests.api.test_action_roles import VIEWER, live_run, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, unowned_live

Stack = tuple[AsyncClient, AsyncEngine]


async def stuck_run(c: AsyncClient, engine: AsyncEngine, n: int) -> str:
    await unowned_live(engine, "refunds", by="seed")
    run_id = str((await c.post("/v1/runs", json=live_run(n), headers=BUILDER)).json()["data"]["runId"])
    async with engine.begin() as conn:
        reason = "Nothing is working on this run: no worker has picked it up for 10 minutes."
        await conn.execute(engine_runs.update().where(engine_runs.c.id == run_id).values(status="stuck", error=reason))
        await conn.execute(engine_work.update().where(engine_work.c.run_id == run_id).values(status="stuck"))
    return run_id


async def test_a_stuck_run_is_retried_from_where_it_stopped(stack: Stack) -> None:  # noqa: F811
    c, engine = stack
    run_id = await stuck_run(c, engine, 1)
    before = (await c.get(f"/v1/runs/{run_id}", headers=BUILDER)).json()["data"]
    assert (before["status"], before["canRetry"]) == ("stuck", True), before
    r = await c.post(f"/v1/runs/{run_id}/retry", headers=BUILDER)
    assert r.status_code == 200, r.text
    assert (r.json()["data"]["status"], r.json()["data"]["canRetry"]) == ("queued", False), r.json()["data"]
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.select(engine_work.c.status, engine_work.c.build).where(engine_work.c.run_id == run_id)
            )
        ).all()
    assert sorted((x.status, x.build) for x in rows) == [("done", ENGINE_BUILD), ("queued", ENGINE_BUILD)], rows


async def test_only_a_stuck_run_is_retried_and_only_by_whoever_may_cancel_it(stack: Stack) -> None:  # noqa: F811
    c, engine = stack
    await unowned_live(engine, "refunds", by="seed")
    queued = str((await c.post("/v1/runs", json=live_run(2), headers=BUILDER)).json()["data"]["runId"])
    refused = await c.post(f"/v1/runs/{queued}/retry", headers=BUILDER)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "run_not_stuck", refused.text
    run_id = await stuck_run(c, engine, 3)
    viewer = await c.post(f"/v1/runs/{run_id}/retry", headers=VIEWER)
    assert viewer.status_code == 403, viewer.text
