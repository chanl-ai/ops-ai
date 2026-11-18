"""The registry tenant preflight script (`make registry-tenant-preflight`), on a scratch database of its own, by failure
mode: it passes a database where every row has one tenant to take; it names a team no tenant holds, a team two
tenants hold and a record two tenants reference; `local` beside one other tenant, a row with a direct reference and a
deployment with no team that a thread names are not counted against it, and one no thread names is."""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from ops_service_kit.ids import new_id, now_iso
from ops_store.testing import NO_SQL_SERVER, sql_server_schema

ROOT = Path(__file__).resolve().parents[2]
# A revision before the one that gives the registry tables a tenant; the preflight reads nothing added since.
BEFORE = "0104_runtime_tables_isolated"


Statement = tuple[str, dict[str, Any]] | sa.Executable


async def sql(url: str | URL, *statements: Statement, admin: bool = False) -> list[Any]:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT") if admin else create_async_engine(url)
    out: list[Any] = []
    async with engine.begin() as c:
        # A test writes every tenant's rows as the login, which SQL Server's security policies filter and block.
        policies = await _policies(c, "OFF") if not admin and c.dialect.name == "mssql" else []
        for statement in statements:
            match statement:
                case (str() as text, dict() as params):
                    r = await c.execute(sa.text(text), params)
                case _:
                    r = await c.execute(statement)
            out.append(r.all() if r.returns_rows else None)
        for name in policies:
            await c.execute(sa.text(f"ALTER SECURITY POLICY {name} WITH (STATE = ON)"))
    await engine.dispose()
    return out


async def _policies(c: AsyncConnection, state: str) -> list[str]:
    q = (
        "SELECT QUOTENAME(SCHEMA_NAME(schema_id)) + '.' + QUOTENAME(name) FROM sys.security_policies "
        "WHERE is_enabled = 1"
    )
    names = [str(n) for (n,) in (await c.execute(sa.text(q))).all()]
    for name in names:
        await c.execute(sa.text(f"ALTER SECURITY POLICY {name} WITH (STATE = {state})"))
    return names


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


def scratch_at(revision: str, database: str = "postgresql") -> tuple[URL, Callable[[], None]]:
    """An agents database of its own at `revision`, and how to drop it. On SQL Server: a scratch database holding the
    chain's golden schema, stepped down to `revision`."""
    if database == "mssql":
        return _mssql_at(revision)
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


def _mssql_at(revision: str) -> tuple[URL, Callable[[], None]]:
    stack = ExitStack()
    raw = stack.enter_context(
        sql_server_schema("agents", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD"))
    )
    if raw is None:
        stack.close()
        pytest.skip(NO_SQL_SERVER)
    url = make_url(raw)
    done = alembic(url, "downgrade", revision)
    if done.returncode != 0:
        stack.close()
        raise AssertionError(done.stderr[-2000:])
    return url, stack.close


@pytest.fixture
def scratch() -> Iterator[URL]:
    url, drop = scratch_at(BEFORE)
    try:
        yield url
    finally:
        drop()


def _preflight(url: URL) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "python", "scripts/registry_tenant_preflight.py"],
        cwd=ROOT,
        env=env_for(url),
        capture_output=True,
        text=True,
        check=False,
    )


DEFAULT = (
    "INSERT INTO team_default_agents (tenant_id, team_id, agent_id, updated_by, updated_at) "
    "VALUES (:tenant, :team, :agent, 'maya@harborpine.example', :at)"
)
DEPLOYMENT = "INSERT INTO deployments (id, graph, channel, created_at, team_id) VALUES (:id, 'g', 'email', :at, '')"


def _columns(name: str, values: dict[str, Any]) -> sa.TableClause:
    return sa.table(name, *(sa.column(k, sa.JSON if k == "meta" else None) for k in values))


def thread(tenant: str, team: str, graph: str = "chat") -> sa.Insert:
    at = now_iso()
    values: dict[str, Any] = {"tenant_id": tenant, "id": new_id("thr"), "graph": graph, "meta": {}, "team_id": team}
    values |= {"created_at": at, "updated_at": at, "status": "idle"}
    return sa.insert(_columns("graph_threads", values)).values(**values)


def agent(agent_id: str, team: str) -> sa.Insert:
    at = now_iso()
    values: dict[str, Any] = {"id": agent_id, "slug": agent_id, "team_id": team, "version": 1, "paused": False}
    values |= {"created_at": at, "updated_at": at}
    return sa.insert(_columns("registry_agents", values)).values(**values)


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
            (DEPLOYMENT, {"id": "dep_mail", "at": now_iso()}),
            (
                "UPDATE graph_threads SET deployment_id = 'dep_mail' WHERE id = "
                "(SELECT MIN(id) FROM graph_threads WHERE tenant_id = 't-harbor')",
                {},
            ),
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
            (DEPLOYMENT, {"id": "dep_idle", "at": now_iso()}),
        )
    )
    done = _preflight(scratch)
    assert done.returncode != 0, done.stderr
    assert done.stdout.splitlines() == [
        "no tenant: team team_payroll holds 2 row(s) in registry_agents",
        "no tenant: deployment dep_idle has no team and no thread",
        "two tenants: team team_lending is in 2 tenants: t-harbor, t-pine",
        "two tenants: registry_agents ag_shared is referenced from 2 tenants: t-harbor, t-pine",
    ], done.stderr
