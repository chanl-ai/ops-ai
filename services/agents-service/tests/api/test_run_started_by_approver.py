"""A run records whether its starter may approve its writes themselves, by failure mode: an
admin's run recorded as not theirs to approve, so its write waits on someone else; a builder's run recorded as theirs,
so it skips a person; and the four-eyes rule (requesterMayDecide off) not counted."""

from __future__ import annotations

import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_engine.store.tables import engine_runs
from tests.api.test_action_roles import live_run, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import ADMIN, person, unowned_live

Stack = tuple[AsyncClient, AsyncEngine]


async def _started_by_approver(c: AsyncClient, engine: AsyncEngine, headers: dict[str, str], n: int) -> bool:
    r = await c.post("/v1/runs", json=live_run(n), headers=headers)
    assert r.status_code == 202, r.text
    run_id = r.json()["data"]["runId"]
    async with engine.connect() as conn:
        q = sa.select(engine_runs.c.started_by_approver).where(engine_runs.c.id == run_id)
        return bool((await conn.execute(q)).scalar_one())


async def test_a_run_records_whether_its_starter_approves_its_writes(stack: Stack) -> None:  # noqa: F811
    c, engine = stack
    await unowned_live(engine, "refunds", by="seed")
    loose_admin = person("priya", "team_ops", "admin", policies={"requesterMayDecide": True})
    assert await _started_by_approver(c, engine, loose_admin, 1), "an admin decides the team's reviews when allowed"
    # A builder decides reviews since D59; one whose role lost reviews.decide does not approve their writes.
    no_decide = person("jo", "team_ops", "builder", unticked=(("reviews", "decide"),))
    assert not await _started_by_approver(c, engine, no_decide, 2), "a role without reviews.decide does not"
    assert not await _started_by_approver(c, engine, ADMIN, 3), "by default someone else decides an admin's run"
