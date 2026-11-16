"""`make registry-tenant-preflight`, run as the operator runs it, on a scratch database of its own, by failure mode: it
passes a database whose teams each map to one tenant; it names a team no tenant holds and a team two tenants hold;
a row with a direct reference or a deployment with no team is not counted against its team."""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.ids import new_id, now_iso

ROOT = Path(__file__).resolve().parents[2]


async def _sql(url: str | URL, *statements: tuple[str, dict[str, Any]], admin: bool = False) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT") if admin else create_async_engine(url)
    async with engine.begin() as c:
        for text, params in statements:
            await c.execute(sa.text(text), params)
    await engine.dispose()


def _env(url: URL) -> dict[str, str]:
    return {**os.environ, "OPS_DATABASE_URL": url.render_as_string(hide_password=False)}


@pytest.fixture
def scratch() -> Iterator[URL]:
    """An agents database of its own at the chain's head, dropped afterwards."""
    raw = os.environ.get("OPS_TEST_DATABASE_URL", "")
    if not raw.startswith("postgresql"):
        pytest.skip("runs on PostgreSQL; set OPS_TEST_DATABASE_URL")
    server = make_url(raw)
    url = server.set(database=f"{server.database}_{new_id('pre')}")
    postgres = server.set(database="postgres")
    asyncio.run(_sql(postgres, (f'CREATE DATABASE "{url.database}"', {}), admin=True))
    try:
        done = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env=_env(url),
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr[-2000:]
        yield url
    finally:
        asyncio.run(_sql(postgres, (f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)', {}), admin=True))


def _preflight(url: URL) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "-s", "registry-tenant-preflight"],
        cwd=ROOT,
        env=_env(url),
        capture_output=True,
        text=True,
        check=False,
    )


AGENT = (
    "INSERT INTO registry_agents (id, slug, team_id, version, paused, created_at, updated_at) "
    "VALUES (:id, :id, :team, 1, false, :at, :at)"
)
THREAD = (
    "INSERT INTO graph_threads (tenant_id, id, graph, meta, team_id, created_at, updated_at, status) "
    "VALUES (:tenant, :id, 'chat', CAST('{}' AS json), :team, :at, :at, 'idle')"
)
DEFAULT = (
    "INSERT INTO team_default_agents (tenant_id, team_id, agent_id, updated_by, updated_at) "
    "VALUES (:tenant, :team, :agent, 'maya@harborpine.example', :at)"
)
DEPLOYMENT = "INSERT INTO deployments (id, graph, channel, created_at, team_id) VALUES (:id, 'g', 'email', :at, '')"


def test_a_database_whose_teams_each_map_to_one_tenant_passes(scratch: URL) -> None:
    at = now_iso()
    asyncio.run(
        _sql(
            scratch,
            (THREAD, {"tenant": "t-harbor", "id": new_id("thr"), "team": "team_claims", "at": at}),
            (AGENT, {"id": new_id("ag"), "team": "team_claims", "at": at}),
            (DEPLOYMENT, {"id": new_id("dep"), "at": at}),
        )
    )
    done = _preflight(scratch)
    assert (done.returncode, done.stdout.strip()) == (
        0,
        "every team the registry and deployment rows need maps to one tenant",
    ), done.stderr


def test_it_names_a_team_no_tenant_holds_and_a_team_two_tenants_hold(scratch: URL) -> None:
    at = now_iso()
    referenced = new_id("ag")
    asyncio.run(
        _sql(
            scratch,
            # team_lending is in two tenants; one of its agents is placed by a direct reference and is not counted.
            (THREAD, {"tenant": "t-harbor", "id": new_id("thr"), "team": "team_lending", "at": at}),
            (THREAD, {"tenant": "t-pine", "id": new_id("thr"), "team": "team_lending", "at": at}),
            (AGENT, {"id": new_id("ag"), "team": "team_lending", "at": at}),
            # team_wires is in two tenants too, but its only agent is someone's default: nothing needs its team.
            (THREAD, {"tenant": "t-harbor", "id": new_id("thr"), "team": "team_wires", "at": at}),
            (DEFAULT, {"tenant": "t-pine", "team": "team_wires", "agent": referenced, "at": at}),
            (AGENT, {"id": referenced, "team": "team_wires", "at": at}),
            # team_payroll is in no tenant at all.
            (AGENT, {"id": new_id("ag"), "team": "team_payroll", "at": at}),
            (AGENT, {"id": new_id("ag"), "team": "team_payroll", "at": at}),
        )
    )
    done = _preflight(scratch)
    assert done.returncode != 0
    assert done.stdout.splitlines() == [
        "no tenant: team team_payroll holds 2 row(s) in registry_agents",
        "two tenants: team team_lending is in 2 tenants: t-harbor, t-pine",
    ], done.stderr
