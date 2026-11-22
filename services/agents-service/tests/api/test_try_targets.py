"""GET /v1/try-targets for one workflow step, by failure mode: the sample is not the tool's last answer in the team's
own live runs (another team's, or a test run's mock), and looking at a try stores a version or a run."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import sqlalchemy as sa
from httpx import AsyncClient

from ops_agents.store.tenancy import LOCAL_TENANT, tenant_scope
from ops_engine.store.tables import engine_definitions, engine_runs, engine_steps

BASIC = Path(__file__).parents[1] / "fixtures" / "engine" / "basic.yaml"


async def _answered(db: Any, *, run: str, team: str, mode: str, at: str, output: dict[str, Any]) -> None:
    """One finished run of refund_check whose lookup step called get_customer and got `output`."""
    async with db.begin() as c:
        await c.execute(
            engine_runs.insert().values(
                id=run,
                tenant_id=LOCAL_TENANT,
                team_id=team,
                workflow_id="refund_check",
                version=1,
                digest="d",
                run_key=run,
                mode=mode,
                status="succeeded",
                created_by="maya.okafor@bank.test",
                created_at=at,
                updated_at=at,
            )
        )
        await c.execute(
            engine_steps.insert().values(
                run_id=run, node_id="lookup", iteration=1, attempt=1, tenant_id=LOCAL_TENANT, status="ok",
                effects="read", key=f"{run}:lookup:1:1", input={"operation": "get_customer"}, port="ok",
                output=output, started_at=at, finished_at=at, node_type="ops.action.tool",
            )
        )  # fmt: skip


async def _count(db: Any, table: sa.Table) -> int:
    async with db.connect() as c:
        return int((await c.execute(sa.select(sa.func.count()).select_from(table))).scalar_one())


async def test_a_steps_sample_is_its_tools_last_answer_in_the_teams_own_live_runs(client: AsyncClient) -> None:
    assert (await client.post("/v1/workflows/definitions", json={"yaml": BASIC.read_text()})).status_code == 201
    db = cast(Any, client)._transport.app.state.runtime.db
    with tenant_scope(LOCAL_TENANT):
        async with db.connect() as c:
            team = (await c.execute(sa.select(engine_definitions.c.team_id))).scalar_one()
        await _answered(db, run="run_old", team=team, mode="live", at="2026-11-20T10:00:00Z", output={"tier": "gold"})
        # Newer, but not this team's real answer: another team's live run and this team's test run.
        await _answered(db, run="run_other", team="team_else", mode="live", at="2026-11-21T10:00:00Z", output={"x": 1})
        await _answered(db, run="run_test", team=team, mode="test", at="2026-11-21T11:00:00Z", output={"mock": True})
        runs, versions = await _count(db, engine_runs), await _count(db, engine_definitions)
        r = await client.get("/v1/try-targets", params={"workflow": "refund_check", "step": "lookup"})
        assert r.status_code == 200, r.text
        step = r.json()["data"]["paths"][0]["steps"][0]
        assert (step["tool"], step["sampleFrom"], step["sample"]) == ("get_customer", "last_run", {"tier": "gold"})
        assert (await _count(db, engine_runs), await _count(db, engine_definitions)) == (runs, versions)
