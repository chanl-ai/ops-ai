"""The revision that stops a run's start-time self-approval from deciding, by failure mode: a run waiting across the
release keeps the yes its starter's roles gave at its start, so its write is approved as theirs after an admin unticked
Approvals decide; and a finished run's record is rewritten, though nothing reads it again."""

from __future__ import annotations

import asyncio
from typing import Any

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.ids import new_id, now_iso

from .test_drop_publish_policies import ROOT

BEFORE = "20261124_0257_skill_owner_ids"
RUN = (
    "INSERT INTO engine_runs (id, tenant_id, team_id, workflow_id, version, digest, run_key, mode, status, created_by,"
    " started_by_approver, created_at, updated_at) VALUES (:id, :tenant, 'team_lending', 'wf_loan_note', 1, 'd', :id,"
    " 'live', :status, 'priya@harborpine.example', :yes, :at, :at)"
)


async def _sql(url: str, text: str, rows: list[dict[str, Any]]) -> list[Any]:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as c:
            await c.execute(sa.text("SET LOCAL row_security = off"))
            if rows:
                await c.execute(sa.text(text), rows)
                return []
            return list((await c.execute(sa.text(text))).all())
    finally:
        await engine.dispose()


def test_unfinished_runs_stop_approving_as_their_starter(emptied_database: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    at = now_iso()
    runs: dict[str, tuple[str, str]] = {}
    for tenant in (new_id("ten"), new_id("ten")):
        for status in ("waiting", "running", "queued", "stuck", "succeeded", "failed"):
            runs[new_id("wfrun")] = (tenant, status)
    rows = [{"id": i, "tenant": t, "status": s, "yes": True, "at": at} for i, (t, s) in runs.items()]
    asyncio.run(_sql(emptied_database, RUN, rows))
    command.upgrade(cfg, "head")
    after: dict[str, bool] = dict(
        asyncio.run(_sql(emptied_database, "SELECT id, started_by_approver FROM engine_runs", []))
    )
    unfinished = {i: after[i] for i, (_, s) in runs.items() if s not in ("succeeded", "failed")}
    finished = {i: after[i] for i, (_, s) in runs.items() if s in ("succeeded", "failed")}
    assert not any(unfinished.values()), unfinished
    assert all(finished.values()), finished
