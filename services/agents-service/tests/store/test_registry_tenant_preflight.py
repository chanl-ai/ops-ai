"""`make registry-tenant-preflight`, run as the operator runs it, on a scratch database of its own, by failure mode: it
passes a database where every row has one tenant to take; it names a team no tenant holds, a team two tenants hold
and a record two tenants reference; `local` beside one other tenant, a row with a direct reference and a deployment
with no team are not counted against it."""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.ids import new_id, now_iso

ROOT = Path(__file__).resolve().parents[2]
# The revision before the one that gives the registry tables a tenant.
BEFORE = "0105_thread_owner_column"


async def sql(url: str | URL, *statements: tuple[str, dict[str, Any]], admin: bool = False) -> list[Any]:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT") if admin else create_async_engine(url)
    out: list[Any] = []
    async with engine.begin() as c:
        for text, params in statements:
            r = await c.execute(sa.text(text), params)
            out.append(r.all() if r.returns_rows else None)
    await engine.dispose()
    return out


def env_for(url: URL, **extra: str) -> dict[str, str]:
    return {**os.environ, "OPS_DATABASE_URL": url.render_as_string(hide_password=False), **extra}


def alembic(url: URL, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=ROOT,
        env=env_for(url, **extra),
        capture_output=True,
        text=True,
        check=False,
    )


def scratch_at(revision: str) -> tuple[URL, Callable[[], None]]:
    """An agents database of its own at `revision`, and how to drop it."""
    raw = os.environ.get("OPS_TEST_DATABASE_URL", "")
    if not raw.startswith("postgresql"):
        pytest.skip("runs on PostgreSQL; set OPS_TEST_DATABASE_URL")
    server = make_url(raw)
    url = server.set(database=f"{server.database}_{new_id('reg')}")
    postgres = server.set(database="postgres")

    def drop() -> None:
        asyncio.run(sql(postgres, (f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)', {}), admin=True))

    asyncio.run(sql(postgres, (f'CREATE DATABASE "{url.database}"', {}), admin=True))
    done = alembic(url, "upgrade", revision)
    if done.returncode != 0:
        drop()
        raise AssertionError(done.stderr[-2000:])
    return url, drop


@pytest.fixture
def scratch() -> Iterator[URL]:
    url, drop = scratch_at(BEFORE)
    try:
        yield url
    finally:
        drop()


def _preflight(url: URL) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "-s", "registry-tenant-preflight"],
        cwd=ROOT,
        env=env_for(url),
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
    "VALUES (:tenant, :id, :graph, CAST('{}' AS json), :team, :at, :at, 'idle')"
)
DEFAULT = (
    "INSERT INTO team_default_agents (tenant_id, team_id, agent_id, updated_by, updated_at) "
    "VALUES (:tenant, :team, :agent, 'maya@harborpine.example', :at)"
)
DEPLOYMENT = "INSERT INTO deployments (id, graph, channel, created_at, team_id) VALUES (:id, 'g', 'email', :at, '')"


def thread(tenant: str, team: str, graph: str = "chat") -> tuple[str, dict[str, Any]]:
    return THREAD, {"tenant": tenant, "id": new_id("thr"), "graph": graph, "team": team, "at": now_iso()}


def agent(agent_id: str, team: str) -> tuple[str, dict[str, Any]]:
    return AGENT, {"id": agent_id, "team": team, "at": now_iso()}


def test_a_database_where_every_row_has_one_tenant_passes(scratch: URL) -> None:
    asyncio.run(
        sql(
            scratch,
            thread("t-harbor", "team_claims"),
            agent(new_id("ag"), "team_claims"),
            # local holds only rows nothing could place: beside one other tenant it does not count.
            thread("local", "team_cards"),
            thread("t-pine", "team_cards"),
            agent(new_id("ag"), "team_cards"),
            (DEPLOYMENT, {"id": new_id("dep"), "at": now_iso()}),
        )
    )
    done = _preflight(scratch)
    assert (done.returncode, done.stdout.strip()) == (0, "every registry and deployment row has one tenant to take"), (
        done.stderr
    )


def test_it_names_a_team_no_tenant_holds_a_team_two_tenants_hold_and_a_record_two_tenants_reference(
    scratch: URL,
) -> None:
    referenced, shared = new_id("ag"), "ag_shared"
    asyncio.run(
        sql(
            scratch,
            # team_lending is in two tenants; its unreferenced agent needs the team.
            thread("t-harbor", "team_lending"),
            thread("t-pine", "team_lending"),
            agent(new_id("ag"), "team_lending"),
            # team_wires is in two tenants too, but its only agent is someone's default: nothing needs its team.
            thread("t-harbor", "team_wires"),
            (DEFAULT, {"tenant": "t-pine", "team": "team_wires", "agent": referenced, "at": now_iso()}),
            agent(referenced, "team_wires"),
            # team_payroll is in no tenant at all.
            agent(new_id("ag"), "team_payroll"),
            agent(new_id("ag"), "team_payroll"),
            # One agent chatted with from two tenants.
            agent(shared, "team_wires"),
            thread("t-harbor", "team_wires", f"agent:{shared}"),
            thread("t-pine", "team_wires", f"agent:{shared}"),
        )
    )
    done = _preflight(scratch)
    assert done.returncode != 0, done.stderr
    assert done.stdout.splitlines() == [
        "no tenant: team team_payroll holds 2 row(s) in registry_agents",
        "two tenants: team team_lending is in 2 tenants: t-harbor, t-pine",
        "two tenants: registry_agents ag_shared is referenced from 2 tenants: t-harbor, t-pine",
    ], done.stderr
