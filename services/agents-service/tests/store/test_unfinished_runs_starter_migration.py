"""The revision that stops a run's start-time self-approval from deciding, by failure mode: a run waiting across the
release keeps the yes its starter's roles gave at its start, so its write is approved as theirs after an admin unticked
Approvals decide; a finished run's record is rewritten, though nothing reads it again; and on SQL Server a deploy,
which migrates with no tenant context, sees no run. Rows are written and read in their tenant's context, as the service
would, and the chain runs with none."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.store.tenancy import tenant_scope, tenant_tx
from ops_service_kit.ids import new_id, now_iso
from ops_store.testing import DATABASES, NO_SQL_SERVER, sql_server_schema

from .test_drop_publish_policies import ROOT

BEFORE = "20261124_0257_skill_owner_ids"
RUN = (
    "INSERT INTO engine_runs (id, tenant_id, team_id, workflow_id, version, digest, run_key, mode, status, created_by,"
    " started_by_approver, created_at, updated_at) VALUES (:id, :tenant, 'team_lending', 'wf_loan_note', 1, 'd', :id,"
    " 'live', :status, 'priya@harborpine.example', :yes, :at, :at)"
)


@pytest.fixture(params=DATABASES)
def url(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """The emptied PostgreSQL test database, or a scratch SQL Server one at head; the chain runs where the rows are,
    since env.py reads the URL from Settings."""
    if request.param == "postgresql":
        yield request.getfixturevalue("emptied_database")
        return
    with sql_server_schema("agents", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")) as u:
        if u is None:
            pytest.skip(NO_SQL_SERVER)
        monkeypatch.setenv("OPS_DATABASE_URL", u)
        yield u


async def _sql(url: str, tenant: str, text: str, rows: list[dict[str, Any]]) -> list[Any]:
    engine = create_async_engine(url)
    try:
        with tenant_scope(tenant):
            async with tenant_tx(engine) as c:
                if rows:
                    await c.execute(sa.text(text), rows)
                    return []
                return list((await c.execute(sa.text(text), {"tenant": tenant})).all())
    finally:
        await engine.dispose()


def test_unfinished_runs_stop_approving_as_their_starter(url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    at = now_iso()
    runs: dict[str, tuple[str, str]] = {}
    tenants = (new_id("ten"), new_id("ten"))
    for tenant in tenants:
        for status in ("waiting", "running", "queued", "stuck", "succeeded", "failed"):
            runs[new_id("wfrun")] = (tenant, status)
    for tenant in tenants:
        rows = [{"id": i, "tenant": t, "status": s, "yes": True, "at": at} for i, (t, s) in runs.items() if t == tenant]
        asyncio.run(_sql(url, tenant, RUN, rows))
    command.upgrade(cfg, "head")
    after: dict[str, bool] = {}
    for tenant in tenants:
        found = asyncio.run(
            _sql(url, tenant, "SELECT id, started_by_approver FROM engine_runs WHERE tenant_id = :tenant", [])
        )
        after.update((i, bool(yes)) for i, yes in found)
    unfinished = {i: after[i] for i, (_, s) in runs.items() if s not in ("succeeded", "failed")}
    finished = {i: after[i] for i, (_, s) in runs.items() if s in ("succeeded", "failed")}
    assert not any(unfinished.values()), unfinished
    assert all(finished.values()), finished
