"""`Store.install_tx(reason)` on each database, by failure mode: an install-wide statement that reaches a table not
marked `system(...)` (policed, unpoliced or unknown to the metadata, or as a login row security does not apply to),
a team filter that passes every team's rows, one that opens a second connection inside a request, one that leaves the
request's connection in its scope afterwards, and the guard on `Store.tx()` loosened by it. `Store.system_tx(reason)`
beside it: a system block that runs as the login instead of the store's system role, or opens with no reason."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects import mssql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.pool import QueuePool
from sqlalchemy.sql.elements import quoted_name

from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.backends import backends
from ops_store.conformance import engine_for, sql_server_database
from ops_store.database import open_database
from ops_store.dialect import dialect_of
from ops_store.isolation import InstallScopeError, NoTenantError
from ops_store.schema import (
    MSSQL_SECURITY,
    TEAM_OWNED,
    TENANT_SCOPED,
    isolation_ddl,
    isolation_drop_ddl,
    role_ddl,
    security_ddl,
    system,
)
from ops_store.store import Store
from ops_store.team_scope import team_visible

SQL_SERVER = (os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD"))
ROLE = "ops_install_scope_test"
# The store's system role: past row security on PostgreSQL, the user the read predicates pass on SQL Server.
SYSTEM = "ops_install_scope_system"
RECOVER = "a restart picking up every tenant's queued work"
CHAIN = "storetestinstall"
SETTINGS = "an install's setting, read by every tenant"

meta = sa.MetaData()
settings = sa.Table(
    "store_test_install_settings",
    meta,
    sa.Column("name", sa.String(64), primary_key=True),
    sa.Column("value", sa.String(64), nullable=False),
    info=system("the install's own settings: no tenant"),
)
notes = sa.Table(
    "store_test_install_notes",
    meta,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    info=TENANT_SCOPED,
)
# Team-owned but with no row policy yet, as many tables still wait: only the query filter and the scope hold it.
loose = sa.Table(
    "store_test_install_loose",
    meta,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False),
    info=TEAM_OWNED,
)


class Install(Store):
    # A role row security applies to: the compose superuser bypasses it, as no runtime login does.
    role = ROLE

    async def setting(self, name: str) -> str | None:
        async with self.install_tx(SETTINGS) as c:
            return await c.scalar(sa.select(settings.c.value).where(settings.c.name == name))

    async def note_ids(self) -> list[str]:
        async with self.tx() as c:
            return [str(i) for i in (await c.execute(sa.select(notes.c.id).order_by(notes.c.id))).scalars()]


class Recovery(Install):
    system_role = SYSTEM

    async def every_note(self) -> tuple[str, list[str]]:
        who = sa.func.current_user() if dialect_of(self.engine) == "postgresql" else sa.func.user_name()
        async with self.system_tx(RECOVER) as c:
            ids = [str(i) for i in (await c.execute(sa.select(notes.c.id).order_by(notes.c.id))).scalars()]
            return str(await c.scalar(sa.select(who))), ids


class Bare(Install):
    # No role: on PostgreSQL the compose superuser, which row security does not apply to.
    role = None


def _mssql_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


@pytest.fixture(params=["postgresql", "mssql"])
async def engine(request: pytest.FixtureRequest) -> AsyncIterator[AsyncEngine]:
    with sql_server_database("ops_install", *SQL_SERVER) as mssql_url:
        if request.param == "mssql":
            if mssql_url is None:
                pytest.skip("set OPS_MSSQL_SERVER and MSSQL_SA_PASSWORD to run on SQL Server")
            url = mssql_url
        else:
            (backend,) = backends(Settings().database_url)
            await (await engine_for(backend)).dispose()
            url = backend.url
        e = open_database(url)
        async with e.begin() as c:
            await _drop(c, request.param)
            await c.run_sync(meta.create_all)
            await c.execute(settings.insert().values(name="region", value="eu"))
            await c.execute(notes.insert(), [{"id": "n1", "tenant_id": "t1"}, {"id": "n2", "tenant_id": "t2"}])
            await c.execute(
                loose.insert(),
                [{"id": "a", "tenant_id": "t1", "team_id": "x"}, {"id": "b", "tenant_id": "t2", "team_id": "y"}],
            )
            if request.param == "postgresql":
                await c.execute(sa.text(role_ddl(ROLE)))
                await c.execute(sa.text(role_ddl(SYSTEM, bypass=True)))
                for t in (settings, notes, loose):
                    await c.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t.name} TO {ROLE}"))
                await c.execute(sa.text(f"GRANT SELECT ON {notes.name} TO {SYSTEM}"))
                for statement in isolation_ddl(notes, "postgresql"):
                    await c.execute(sa.text(statement))
            else:
                await c.execute(sa.text(f"IF USER_ID(N'{SYSTEM}') IS NULL CREATE USER {SYSTEM} WITHOUT LOGIN"))
                await c.execute(sa.text(f"GRANT SELECT ON {notes.name} TO {SYSTEM}"))
                for statement in security_ddl(CHAIN, [notes], column_type=_mssql_type, system_user=SYSTEM):
                    await c.execute(sa.text(statement))
        yield e
        async with e.begin() as c:
            await _drop(c, request.param)
        await e.dispose()


async def _drop(c: Any, dialect: str) -> None:
    if dialect == "mssql":
        for statement in isolation_drop_ddl(notes, "mssql"):
            await c.execute(sa.text(statement))
        for part in ("read", "write"):
            fn = f"{MSSQL_SECURITY}.{CHAIN}_tenant_{part}"
            await c.execute(sa.text(f"IF OBJECT_ID(N'{fn}', N'IF') IS NOT NULL DROP FUNCTION {fn}"))
    await c.run_sync(meta.drop_all)


async def test_an_install_wide_transaction_reads_install_tables_and_no_tenant_row(engine: AsyncEngine) -> None:
    st = Install(engine)
    with isolation.scope("t1", None):
        assert await st.note_ids() == ["n1"], "the policy shows a tenant its own row"
    async with st.install_tx(SETTINGS) as c:
        assert await c.scalar(sa.select(settings.c.value)) == "eu"
        with pytest.raises(NoTenantError):
            isolation.tenant()
    with pytest.raises(NoTenantError):
        await st.note_ids()


async def test_a_system_block_reads_every_tenants_rows_as_the_stores_system_role_and_needs_a_reason(
    engine: AsyncEngine,
) -> None:
    st = Recovery(engine)
    assert await st.every_note() == (SYSTEM, ["n1", "n2"])
    with isolation.scope("t1", None):
        assert await st.note_ids() == ["n1"], "the store's own tx() still sees one tenant"
    with pytest.raises(ValueError, match="needs a reason"):
        async with st.system_tx(" "):
            pass


@pytest.mark.parametrize("role", [ROLE, None], ids=["policed-role", "no-role"])
async def test_an_install_block_refuses_every_statement_on_a_table_not_marked_system(
    engine: AsyncEngine, role: str | None
) -> None:
    """With no role (the compose superuser, past row security on PostgreSQL) as with one, on a policed table, on one
    with no policy, and in a subquery: refused by name before the database sees it."""
    st = Install(engine) if role else Bare(engine)
    refused: list[str] = []
    for statement in (
        sa.select(notes.c.id),
        sa.select(loose.c.id),
        notes.insert().values(id="n3", tenant_id="t1"),
        sa.select(settings.c.value).where(settings.c.name.in_(sa.select(loose.c.id))),
        sa.select(settings.c.value).where(sa.exists(sa.select(notes.c.id))),
        sa.select(sa.table("store_test_install_loose", sa.column("id"))),
    ):
        try:
            async with st.install_tx(SETTINGS) as c:
                result = await c.execute(statement)
                refused.append(f"ran: {list(result.scalars()) if result.returns_rows else 'wrote'}")
        except InstallScopeError:
            refused.append("refused")
        except DBAPIError as e:
            refused.append(f"the database refused it: {type(e.orig).__name__}")
    assert refused == ["refused"] * 6, refused
    async with st.install_tx(SETTINGS) as c:
        assert await c.scalar(sa.select(settings.c.value)) == "eu", "a system table is still read"
    with isolation.scope("t1", None):
        assert sorted(await _loose(engine, role)) == ["a"], "the caller's own block still reads"


async def _loose(engine: AsyncEngine, role: str | None) -> list[str]:
    async with isolation.isolated_tx(engine, role=role) as c:
        return [str(i) for i in (await c.execute(sa.select(loose.c.id).where(loose.c.tenant_id == "t1"))).scalars()]


async def test_an_install_block_refuses_raw_sql(engine: AsyncEngine) -> None:
    """Text with no table metadata says nothing the refusal can check, so it is refused, as SQL for the driver."""
    st = Install(engine)
    raw = "SELECT id FROM store_test_install_loose"
    runs: list[Callable[[AsyncConnection], Awaitable[object]]] = [
        lambda c: c.execute(sa.text(raw)),
        lambda c: c.exec_driver_sql(raw),
        lambda c: c.execute(sa.select(settings.c.value).where(sa.text("1 = 1"))),
    ]
    for run in runs:
        with pytest.raises(InstallScopeError):
            async with st.install_tx(SETTINGS) as c:
                await run(c)


def test_the_team_filter_refuses_an_install_block() -> None:
    """No acting team in an install block is no team at all, not every team."""
    with isolation.install_wide(SETTINGS), pytest.raises(InstallScopeError):
        team_visible(loose)
    with isolation.install_wide(SETTINGS), isolation.scope("t1", "x"):
        assert str(team_visible(loose)) == str(loose.c.team_id == "x"), "a team scope inside reads its team"


async def test_inside_a_request_it_reuses_the_one_connection_and_restores_the_callers_scope(
    engine: AsyncEngine,
) -> None:
    st = Install(engine)
    checkouts: list[object] = []

    def checked_out(dbapi_conn: object, *_: object) -> None:
        checkouts.append(dbapi_conn)

    event.listen(engine.sync_engine.pool, "checkout", checked_out)
    try:
        with isolation.scope("t1", None):
            async with isolation.request_transaction():
                before = await st.note_ids()
                region = await st.setting("region")
                async with st.tx() as outer:
                    async with st.install_tx(SETTINGS) as c:
                        hidden = list((await c.execute(sa.select(settings.c.value))).scalars())
                    # The block around it reads on as the caller, with no statement of its own to set that again.
                    restored = list((await outer.execute(sa.select(notes.c.id))).scalars())
                after = await st.note_ids()
    finally:
        event.remove(engine.sync_engine.pool, "checkout", checked_out)
    assert (before, region, hidden, restored, after) == (["n1"], "eu", ["eu"], ["n1"], ["n1"])
    assert len(checkouts) == 1, f"{len(checkouts)} checkouts in one request on {dialect_of(engine)}"


async def test_a_statement_cancelled_mid_flight_raises_the_cancellation_and_returns_the_connection(
    engine: AsyncEngine,
) -> None:
    """Cancelled inside a block whose scope differs from the one around it: the restore that follows meets a
    transaction the cancellation left unusable, and must neither replace the cancellation nor leak the connection."""
    st = Install(engine)
    sleep = (
        sa.select(sa.func.pg_sleep(5)) if dialect_of(engine) == "postgresql" else sa.text("WAITFOR DELAY '00:00:05'")
    )
    started = asyncio.Event()

    async def call() -> None:
        with isolation.scope("t1", None):
            async with isolation.request_transaction(), st.install_tx(SETTINGS):
                with isolation.scope("t1", None):
                    async with st.tx() as c:
                        started.set()
                        await c.execute(sleep)

    task = asyncio.create_task(call())
    await started.wait()
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    pool = engine.sync_engine.pool
    assert isinstance(pool, QueuePool)
    assert pool.checkedout() == 0, "the cancelled request's connection went back to the pool"


async def test_an_install_block_judges_a_statement_by_its_tables_not_its_columns(engine: AsyncEngine) -> None:
    """count(*), a literal, a function or select(1) over a system table runs; so does a statement with no table. A
    table not marked system anywhere (a CTE, a join, a DML target's subquery) is refused."""
    st = Install(engine)
    over_loose = sa.select(loose.c.id).cte("ids")
    allowed: list[sa.Executable] = [
        sa.select(sa.func.count()).select_from(settings),
        sa.select(sa.literal(1)).select_from(settings),
        sa.select(sa.func.coalesce(sa.func.max(settings.c.value), "none")),
        sa.select(sa.literal_column("1", sa.Integer)).select_from(settings),
        sa.select(sa.literal(1)),
        sa.select(sa.func.count()).select_from(sa.select(settings.c.name).cte("names")),
    ]
    refused: list[sa.Executable] = [
        sa.select(sa.func.count()).select_from(over_loose),
        sa.select(settings.c.value).join_from(settings, loose, loose.c.id == settings.c.name),
        settings.update().where(settings.c.name.in_(sa.select(loose.c.id))).values(value="x"),
        sa.select(sa.literal_column("1 + (SELECT count(*) FROM store_test_install_loose)", sa.Integer)),
    ]
    ran: list[str] = []
    for statement in [*allowed, *refused]:
        try:
            async with st.install_tx(SETTINGS) as c:
                await c.execute(statement)
            ran.append("ran")
        except InstallScopeError:
            ran.append("refused")
    assert ran == ["ran"] * len(allowed) + ["refused"] * len(refused), ran


async def _outcomes(st: Store, statements: list[sa.Executable]) -> list[str]:
    out: list[str] = []
    for statement in statements:
        try:
            async with st.install_tx(SETTINGS) as c:
                await c.execute(statement)
            out.append("ran")
        except InstallScopeError:
            out.append("refused")
        except Exception as e:  # what the database or the compiler made of a statement that reached it
            out.append(f"reached the database: {type(e).__name__}")
    return out


async def test_an_install_block_refuses_a_column_of_another_table_and_sql_text_outside_the_tree(
    engine: AsyncEngine,
) -> None:
    """A column whose table is not marked system, wherever it sits (an UPDATE's value, which renders UPDATE ... FROM;
    a DELETE's RETURNING, which renders DELETE ... USING), and SQL text the statement carries beside its tree (a custom
    operator, a prefix, a suffix, a collation, an EXTRACT field, an unquoted name), are refused before they are sent."""
    st = Install(engine)
    raw = "IN (SELECT id FROM store_test_install_loose) --"
    statements: list[sa.Executable] = [
        settings.update().values(value=loose.c.id),
        settings.delete().where(settings.c.name == loose.c.id).returning(loose.c.id),
        sa.select(settings.c.value).where(settings.c.name.op(raw)(1)),
        sa.select(settings.c.value).where(settings.c.name.bool_op(raw)(1)),
        sa.select(settings.c.value).prefix_with("/* raw */"),
        sa.select(settings.c.value).suffix_with("/* raw */"),
        sa.select(settings.c.value).with_statement_hint("/* raw */"),
        sa.select(settings.c.value.collate("Latin1_General_CI_AS (SELECT 1)")),
        sa.select(sa.extract("year FROM now()) --", sa.func.count())).select_from(settings),
        sa.select(sa.column(quoted_name("(SELECT count(*) FROM store_test_install_loose)", quote=False), sa.Integer)),
    ]
    assert await _outcomes(st, statements) == ["refused"] * len(statements)
    async with st.install_tx(SETTINGS) as c:
        assert await c.scalar(sa.select(settings.c.value)) == "eu", "a system table is still read"
