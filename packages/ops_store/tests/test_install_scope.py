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

from ops_service_kit.listing import ListParams
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.backends import backends
from ops_store.conformance import engine_for, sql_server_database
from ops_store.database import open_database
from ops_store.dialect import db_epoch, db_now, dialect_of, lock_key
from ops_store.isolation import InstallScopeError, NoTenantError
from ops_store.listing import LISTED, list_page
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
    sa.Column("name", sa.String(64), primary_key=True, info=LISTED),
    sa.Column("value", sa.String(64), nullable=False),
    info=system("the install's own settings: no tenant"),
)
# A second install table, so a block can declare one and be refused the other.
limits = sa.Table(
    "store_test_install_limits",
    meta,
    sa.Column("name", sa.String(64), primary_key=True),
    info=system("the install's own limits: no tenant"),
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
        async with self.install_tx(SETTINGS, tables=(settings,)) as c:
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
                for t in (settings, limits, notes, loose):
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
    async with st.install_tx(SETTINGS, tables=(settings,)) as c:
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
            async with st.install_tx(SETTINGS, tables=(settings,)) as c:
                result = await c.execute(statement)
                refused.append(f"ran: {list(result.scalars()) if result.returns_rows else 'wrote'}")
        except InstallScopeError:
            refused.append("refused")
        except DBAPIError as e:
            refused.append(f"the database refused it: {type(e.orig).__name__}")
    assert refused == ["refused"] * 6, refused
    async with st.install_tx(SETTINGS, tables=(settings,)) as c:
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
            async with st.install_tx(SETTINGS, tables=(settings,)) as c:
                await run(c)


def test_the_team_filter_refuses_an_install_block() -> None:
    """No acting team in an install block is no team at all, not every team."""
    with isolation.install_wide(SETTINGS, tables=(settings,)), pytest.raises(InstallScopeError):
        team_visible(loose)
    with isolation.install_wide(SETTINGS, tables=(settings,)), isolation.scope("t1", "x"):
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
                    async with st.install_tx(SETTINGS, tables=(settings,)) as c:
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
            async with isolation.request_transaction(), st.install_tx(SETTINGS, tables=(settings,)):
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
            async with st.install_tx(SETTINGS, tables=(settings,)) as c:
                await c.execute(statement)
            ran.append("ran")
        except InstallScopeError:
            ran.append("refused")
    assert ran == ["ran"] * len(allowed) + ["refused"] * len(refused), ran


async def _outcomes(st: Store, statements: list[sa.Executable]) -> list[str]:
    out: list[str] = []
    for statement in statements:
        try:
            async with st.install_tx(SETTINGS, tables=(settings,)) as c:
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
    async with st.install_tx(SETTINGS, tables=(settings,)) as c:
        assert await c.scalar(sa.select(settings.c.value)) == "eu", "a system table is still read"


async def test_an_install_block_calls_only_the_listed_functions(engine: AsyncEngine) -> None:
    """A database function can read any table (or a view over one), so only the listed functions and the database's
    clock run; any other name, a schema-qualified one, or a function used as a table is refused."""
    st = Install(engine)
    allowed: list[sa.Executable] = [
        sa.select(sa.func.count(settings.c.name), sa.func.coalesce(sa.func.max(settings.c.value), "none")),
        # The earliest due time of a timer table, picked by the database rather than by reading every row.
        sa.select(sa.func.min(settings.c.value)),
        sa.select(db_now(), db_epoch()),
    ]
    user = sa.func.current_user() if dialect_of(engine) == "postgresql" else sa.func.user_name()
    refused: list[sa.Executable] = [
        sa.select(user),
        sa.select(sa.func.sum(sa.literal(2, sa.Integer))).select_from(settings),
        sa.select(settings.c.value).where(settings.c.name == sa.func.store_test_install_reader()),
        sa.select(sa.func.dbo.count(settings.c.name)),
        sa.select(sa.func.count().table_valued("n")),
    ]
    out = await _outcomes(st, [*allowed, *refused])
    assert out == ["ran"] * len(allowed) + ["refused"] * len(refused), out


async def test_an_install_block_takes_the_dialects_key_lock_and_nothing_written_like_it(engine: AsyncEngine) -> None:
    """`lock_key` runs inside an install block and holds a second block on the same key until the first ends. The
    same call written by hand (the function, the procedure, its exact text) and any other procedure stay refused."""
    st = Install(engine)
    held, release = asyncio.Event(), asyncio.Event()
    order: list[str] = []

    async def first() -> None:
        async with st.install_tx(SETTINGS, tables=(settings,)) as c:
            await lock_key(c, "thread:t1")
            order.append("first locked")
            held.set()
            await release.wait()
            order.append("first ends")

    async def second() -> None:
        await held.wait()
        async with st.install_tx(SETTINGS, tables=(settings,)) as c:
            await lock_key(c, "thread:t1")
            order.append("second locked")

    one, two = asyncio.create_task(first()), asyncio.create_task(second())
    locked = asyncio.create_task(held.wait())
    await asyncio.wait({one, locked}, timeout=10, return_when=asyncio.FIRST_COMPLETED)
    if one.done():
        two.cancel()
        locked.cancel()
        one.result()  # the first block failed before it held the key: raise what refused it
    await asyncio.sleep(0.5)
    assert not two.done(), "the second block waits on the key"
    release.set()
    await asyncio.wait_for(asyncio.gather(one, two), 10)
    assert order == ["first locked", "first ends", "second locked"]
    applock = (
        "DECLARE @granted int; EXEC @granted = sp_getapplock @Resource = 'k', @LockMode = 'Exclusive', "
        "@LockOwner = 'Transaction', @LockTimeout = -1; "
        "IF @granted < 0 THROW 51000, 'ops_store.lock_key: lock not granted', 1;"
    )
    refused: list[sa.Executable] = [
        sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended("k", 0))),
        sa.select(sa.func.pg_advisory_xact_lock(1)),
        sa.text(applock),
        sa.text("EXEC sp_executesql N'SELECT id FROM store_test_install_loose'"),
        sa.text("EXEC xp_cmdshell 'dir'"),
        sa.text("SELECT id FROM store_test_install_loose"),
    ]
    assert await _outcomes(st, refused) == ["refused"] * len(refused)


async def test_a_list_over_a_system_table_is_searched_and_sorted_inside_an_install_block(engine: AsyncEngine) -> None:
    """`list_page`'s search (`lower(...) LIKE`), sort and counts run in install scope: the functions it emits are
    listed, and nothing wider."""
    st = Install(engine)
    async with engine.begin() as c:
        await c.execute(settings.insert(), [{"name": "Retention", "value": "30d"}, {"name": "retry", "value": "3"}])
    asked = ListParams(search="RET", sort_by="name", sort_order="desc")
    async with st.install_tx(SETTINGS, tables=(settings,)) as c:
        page = await list_page(
            c,
            sa.select(settings.c.name),
            asked,
            search=[settings.c.name],
            sortable={"name": settings.c.name},
            default_sort=settings.c.name,
            facets={"value": settings.c.value},
        )
    assert sorted(r["name"] for r in page["data"]) == ["Retention", "retry"] and page["pagination"]["total"] == 2
    assert page["facets"] == {"value": {"30d": 1, "3": 1}}


async def test_an_install_block_touches_only_the_tables_it_declared(engine: AsyncEngine) -> None:
    """A block names the system tables it touches; another system table, in its own statement or in one a caller
    passed in, is refused at execute time. Inside one request, a second block with other tables is held to its own,
    and the block around it to the ones it declared. A table not marked system cannot be declared."""
    st = Install(engine)
    passed_in = limits.insert().values(name="cap")
    outcomes: list[str] = []
    for declared, statement in [
        ((settings,), sa.select(settings.c.value)),
        ((limits,), sa.select(settings.c.value)),
        ((settings,), passed_in),
        ((settings, limits), sa.select(settings.c.value).join_from(settings, limits, limits.c.name == settings.c.name)),
    ]:
        try:
            async with st.install_tx(SETTINGS, tables=declared) as c:
                await c.execute(statement)
            outcomes.append("ran")
        except InstallScopeError:
            outcomes.append("refused")
    assert outcomes == ["ran", "refused", "refused", "ran"]
    with isolation.scope("t1", None):
        async with isolation.request_transaction(), st.install_tx(SETTINGS, tables=(settings,)) as outer:
            async with st.install_tx(SETTINGS, tables=(limits,)) as inner:
                with pytest.raises(InstallScopeError):
                    await inner.execute(sa.select(settings.c.value))
                assert await inner.scalar(sa.select(sa.func.count()).select_from(limits)) == 0
            assert await outer.scalar(sa.select(settings.c.value)) == "eu"
            with pytest.raises(InstallScopeError):
                await outer.execute(sa.select(limits.c.name))
    with pytest.raises(InstallScopeError, match="cannot be declared"):
        async with st.install_tx(SETTINGS, tables=(notes,)):
            pass


def test_an_install_block_that_names_an_empty_set_does_not_open() -> None:
    """`tables` is required, so no block reaches every system table; an empty set raises before any connection."""
    with pytest.raises(ValueError, match="at least one table"), isolation.install_wide(SETTINGS, tables=()):
        pass


class _Spelled(sa.types.UserDefinedType[str]):
    """A cast type whose spelling is whatever its author wrote: SQL the guard cannot read."""

    cache_ok = True

    def get_col_spec(self, **_: Any) -> str:
        return "VARCHAR(64)"


class _Picked(sa.types.TypeDecorator[str]):
    """A decorator over a plain string that renders another type on each database."""

    impl = sa.String(64)
    cache_ok = True

    def load_dialect_impl(self, dialect: sa.Dialect) -> sa.types.TypeEngine[Any]:
        return _Spelled()


async def test_an_install_block_holds_a_declared_table_by_identity_not_by_name(engine: AsyncEngine) -> None:
    """A same-named table in another schema (here the default one, so it would run), a schema map that renames the
    declared table's schema, and a cast to a type whose spelling is free text each reach past the declared table."""
    st = Install(engine)
    schema = "public" if dialect_of(engine) == "postgresql" else "dbo"
    twin = sa.Table(
        settings.name,
        sa.MetaData(),
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("value", sa.String(64)),
        schema=schema,
        info=system("a twin of the install's settings"),
    )
    statements: list[sa.Executable] = [
        sa.select(twin.c.value),
        sa.select(settings.c.value).execution_options(schema_translate_map={None: schema}),
        sa.select(sa.cast(settings.c.value, _Spelled())),
        sa.select(sa.cast(settings.c.value, _Picked())),
        sa.select(sa.cast(settings.c.value, sa.String(64, collation="Latin1_General_CI_AS (SELECT 1)"))),
    ]
    out: list[str] = []
    for statement in statements:
        try:
            async with st.install_tx(SETTINGS, tables=(settings,)) as c:
                await c.execute(statement)
            out.append("ran")
        except InstallScopeError:
            out.append("refused")
        except Exception as e:  # what the database made of a statement that reached it
            out.append(f"reached the database: {type(e).__name__}")
    assert out == ["refused"] * len(statements), out
    with pytest.raises(InstallScopeError):
        async with st.install_tx(SETTINGS, tables=(settings,)) as c:
            await c.execution_options(schema_translate_map={None: schema})
            await c.execute(sa.select(settings.c.value))
    async with st.install_tx(SETTINGS, tables=(settings,)) as c:
        assert await c.scalar(sa.select(sa.cast(settings.c.value, sa.String(64)))) == "eu", "a plain cast still runs"
