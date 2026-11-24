"""Bulk redrive, by failure mode: a bulk action touches a run outside its filter."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_engine.store.tables import engine_runs
from tests.api.test_action_roles import live_run, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, unowned_live

Stack = tuple[AsyncClient, AsyncEngine]


async def ended(c: AsyncClient, engine: AsyncEngine, n: int, status: str, code: str, **values: Any) -> str:
    run_id = str((await c.post("/v1/runs", json=live_run(n), headers=BUILDER)).json()["data"]["runId"])
    failure = {"kind": "upstream" if code == "tool_failed" else "outage", "code": code}
    async with engine.begin() as conn:
        await conn.execute(
            engine_runs.update()
            .where(engine_runs.c.id == run_id)
            .values(status=status, error="it broke", failure=failure, **values)
        )
    return run_id


async def test_a_bulk_redrive_touches_only_the_runs_its_filter_matches(stack: Stack) -> None:  # noqa: F811
    c, engine = stack
    await unowned_live(engine, "refunds", by="seed")
    matched = await ended(c, engine, 1, "failed", "tool_failed")
    other_code = await ended(c, engine, 2, "failed", "unavailable")
    too_old = await ended(c, engine, 3, "stuck", "tool_failed", created_at="2001-01-01T00:00:00Z")
    filt = {"code": "tool_failed", "workflowId": "refunds", "createdFrom": "2020-01-01T00:00:00Z"}
    r = await c.post("/v1/runs/bulk", json={"action": "redrive", "filter": filt}, headers=BUILDER)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["changed"] == [matched], r.json()
    async with engine.connect() as conn:
        found = (await conn.execute(sa.select(engine_runs.c.id, engine_runs.c.status))).all()
    statuses = {row.id: row.status for row in found}
    assert (statuses[matched], statuses[other_code], statuses[too_old]) == ("queued", "failed", "stuck"), statuses
    # A single redrive records who redrove the run on its events, where the run page's history reads it from.
    r = await c.post(f"/v1/runs/{other_code}/redrive", headers=BUILDER)
    assert r.status_code == 200, r.text
    events = await c.get(f"/v1/runs/{other_code}/events", params={"follow": "false"}, headers=BUILDER)
    assert '"type": "redriven"' in events.text or '"type":"redriven"' in events.text, events.text[:2000]
