"""Generated isolation policies on PostgreSQL (c-410), by failure mode, with raw SQL and no WHERE clause so only the
policy can filter: a team transaction that reads another team's rows; a team transaction that writes another team's
or a null-team row; a tenant-wide transaction that reads another tenant; a team table left with a tenant-only policy,
with no policy, or with a second permissive policy beside its own (PostgreSQL ORs them). Each of the last three must
fail the suite naming the table. SQL Server runs the same suite in c-419."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.settings import Settings
from ops_store.backends import backends
from ops_store.conformance import engine_for, isolation_suite
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, team_owned

ROLE = "ops_isolation_test"
meta = sa.MetaData()


def _table(name: str, team: str | None, *, nullable: bool = True, team_marker: bool = True) -> sa.Table:
    cols: list[sa.Column[str]] = [
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("body", sa.String(32), nullable=False),
    ]
    info = dict(TENANT_SCOPED)
    if team is not None:
        cols.append(sa.Column(team, sa.String(64), nullable=nullable))
        if team_marker:
            info |= team_owned(team) if team != "team_id" else TEAM_OWNED
    return sa.Table(name, meta, *cols, info=info)


team_shared = _table("store_test_iso_team_shared", "team_id")
team_strict = _table("store_test_iso_team_strict", "team_id", nullable=False)
named_team = _table("store_test_iso_named_team", "team")
tenant_only = _table("store_test_iso_tenant_only", None)
TABLES = [team_shared, team_strict, named_team, tenant_only]


async def _apply(engine: AsyncEngine, table: sa.Table, kind: str | None = None) -> None:
    async with engine.begin() as c:
        for statement in isolation_ddl(table, "postgresql", kind=kind):  # pyright: ignore[reportArgumentType]
            await c.execute(sa.text(statement))


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    (b,) = backends(Settings().database_url)
    e = await engine_for(b)
    async with e.begin() as c:
        await c.run_sync(meta.drop_all)
        await c.run_sync(meta.create_all)
        await c.execute(
            sa.text(f"DO $$ BEGIN CREATE ROLE {ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
        )
        for t in TABLES:
            await c.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t.name} TO {ROLE}"))
    for t in TABLES:
        await _apply(e, t)
    yield e
    async with e.begin() as c:
        await c.run_sync(meta.drop_all)
    await e.dispose()


async def test_each_generated_policy_holds_a_team_to_its_rows_and_a_tenant_to_its_teams(engine: AsyncEngine) -> None:
    assert await isolation_suite(engine, TABLES, role=ROLE) == []


async def test_a_team_table_with_a_tenant_only_policy_is_named(engine: AsyncEngine) -> None:
    await _apply(engine, team_strict, "tenant")
    failures = await isolation_suite(engine, TABLES, role=ROLE)
    assert failures and {f.split(":")[0] for f in failures} == {team_strict.name}, failures


async def test_a_team_table_with_its_policy_dropped_is_named(engine: AsyncEngine) -> None:
    async with engine.begin() as c:
        await c.execute(sa.text(f"DROP POLICY {named_team.name}_isolation ON {named_team.name}"))
    failures = await isolation_suite(engine, TABLES, role=ROLE)
    assert failures and {f.split(":")[0] for f in failures} == {named_team.name}, failures


async def test_a_second_permissive_policy_beside_the_generated_one_is_named(engine: AsyncEngine) -> None:
    t = team_shared.name
    async with engine.begin() as c:
        await c.execute(
            sa.text(f"CREATE POLICY {t}_tenant ON {t} USING (tenant_id = current_setting('app.tenant_id', true))")
        )
    failures = await isolation_suite(engine, TABLES, role=ROLE)
    assert failures and {f.split(":")[0] for f in failures} == {t}, failures


def test_the_generator_refuses_a_team_owned_table_without_its_team_column() -> None:
    broken = sa.Table(
        "store_test_iso_broken",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(8)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )
    with pytest.raises(ValueError, match="team column"):
        isolation_ddl(broken, "postgresql")
