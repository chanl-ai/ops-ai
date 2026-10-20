"""ops_store.dialect (c-343), by failure mode: a helper that renders the wrong form for a database (compiled for
PostgreSQL and SQL Server, no server needed), a row lock or claim that does not hold a second writer, an upsert that
inserts twice, a clock read from the host, and a tenant setting that outlives its transaction. The live cases run on
the PostgreSQL conformance database; SQL Server runs them in c-345."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mssql, mysql, postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.settings import Settings
from ops_store.backends import backends
from ops_store.conformance import engine_for
from ops_store.dialect import (
    claim,
    db_after,
    db_epoch,
    db_now,
    dialect_of,
    full_text,
    insert_ignore,
    lock_key,
    locked,
    tenant_tx,
    upsert,
)
from ops_store.search import contains

meta = sa.MetaData()
work = sa.Table(
    "store_test_dialect_work",
    meta,
    sa.Column("id", sa.String(16), primary_key=True),
    sa.Column("due", sa.Float(asdecimal=False), nullable=False),
    sa.Column("body", sa.JSON),
    sa.Column("n", sa.Integer, nullable=False, default=0),
)
PG, MS = postgresql.dialect(), mssql.dialect()


def sql(stmt: Any, dialect: sa.Dialect) -> str:
    return " ".join(str(stmt.compile(dialect=dialect)).split())


# Compiled for each database ---------------------------------------------------------------------------------------


def test_a_row_lock_renders_on_both_databases() -> None:
    q = locked(sa.select(work).where(work.c.id == "a"), work)
    assert sql(q, PG).endswith("FOR UPDATE")
    assert "FROM store_test_dialect_work WITH (UPDLOCK, ROWLOCK)" in sql(q, MS)
    # The bare form this replaces: SQL Server receives a plain SELECT, the lock gone with no error.
    assert "WITH (" not in sql(sa.select(work).with_for_update(), MS)


def test_a_claim_skips_held_rows_and_takes_the_oldest_on_both_databases() -> None:
    q = claim(sa.select(work).order_by(work.c.due).limit(1), work)
    assert sql(q, PG).endswith("LIMIT %(param_1)s::INTEGER FOR UPDATE SKIP LOCKED")
    ms = sql(q, MS)
    assert (
        ms.startswith("SELECT TOP")
        and "WITH (UPDLOCK, ROWLOCK, READPAST)" in ms
        and ms.endswith("ORDER BY store_test_dialect_work.due")
    )


def test_an_upsert_renders_on_conflict_and_merge() -> None:
    row = {"id": "a", "due": 1.0, "n": 1}
    assert "ON CONFLICT (id) DO UPDATE SET due = excluded.due, n = excluded.n" in sql(
        upsert(PG, work, row, keys=["id"]), PG
    )
    ms = sql(upsert(MS, work, row, keys=["id"], returning=["n"]), MS)
    assert ms.startswith("MERGE INTO store_test_dialect_work WITH (HOLDLOCK) AS t USING (VALUES (:v_0, :v_1, :v_2))")
    assert "WHEN MATCHED THEN UPDATE SET t.due = s.due, t.n = s.n" in ms and ms.endswith("OUTPUT inserted.n;")


def test_an_insert_that_ignores_a_taken_key_renders_on_both_databases() -> None:
    assert sql(insert_ignore(PG, work, {"id": "a", "due": 1.0}, keys=["id"]), PG).endswith(
        "ON CONFLICT (id) DO NOTHING"
    )
    ms = sql(insert_ignore(MS, work, {"id": "a", "due": 1.0}, keys=["id"]), MS)
    assert "WHERE NOT (EXISTS (SELECT" in ms and "WITH (UPDLOCK, HOLDLOCK)" in ms


def test_the_clock_is_the_database_s_on_both_databases() -> None:
    q = sa.select(db_now(), db_epoch(), db_after(sa.literal(5.0)))
    pg = sql(q, PG)
    assert "now() AS" in pg and "extract(epoch from now())" in pg and "(now() + make_interval(secs =>" in pg
    ms = sql(q, MS)
    assert "SYSDATETIMEOFFSET()" in ms and "DATEDIFF_BIG(millisecond, '1970-01-01', SYSUTCDATETIME())" in ms
    assert "DATEADD(millisecond" in ms and "CURRENT_TIMESTAMP" not in ms


def test_full_text_renders_a_match_and_a_contains_predicate() -> None:
    q = sa.select(work.c.id).where(full_text(MS, work.c.id, 'rate NEAR "x"'))
    assert sql(q, MS).endswith("WHERE CONTAINS(store_test_dialect_work.id, :param_1)")
    assert "@@ plainto_tsquery" in sql(sa.select(work.c.id).where(full_text(PG, work.c.id, "rate")), PG)


def test_a_database_that_is_not_supported_is_refused() -> None:
    with pytest.raises(NotImplementedError, match="mysql is not a supported database"):
        dialect_of(mysql.dialect())


# Live on PostgreSQL -----------------------------------------------------------------------------------------------


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    (b,) = backends(Settings().database_url)
    e = await engine_for(b)
    async with e.begin() as c:
        await c.run_sync(meta.drop_all)
        await c.run_sync(meta.create_all)
        await c.execute(work.insert(), [{"id": "old", "due": 1.0, "n": 0}, {"id": "new", "due": 2.0, "n": 0}])
    yield e
    async with e.begin() as c:
        await c.run_sync(meta.drop_all)
    await e.dispose()


async def _waits(c: AsyncConnection, stmt: Any) -> bool:
    """Whether `stmt` waits on another transaction's lock: PostgreSQL gives up after lock_timeout instead."""
    await c.execute(sa.text("SET LOCAL lock_timeout = '300ms'"))
    try:
        await c.execute(stmt)
    except DBAPIError as e:
        assert "lock timeout" in str(e).lower() or "canceling statement due to lock timeout" in str(e)
        return True
    return False


async def test_a_locked_row_holds_a_second_writer_until_the_first_commits(engine: AsyncEngine) -> None:
    row = locked(sa.select(work).where(work.c.id == "old"), work)
    async with engine.connect() as a, engine.connect() as b:
        await a.begin()
        await a.execute(row)
        await b.begin()
        assert await _waits(b, row), "a second writer read the row while the first held it"
        await b.rollback()
        await a.commit()
        await b.begin()
        assert not await _waits(b, row)
        await b.rollback()


async def test_a_claim_takes_the_oldest_due_row_and_a_second_claim_skips_it(engine: AsyncEngine) -> None:
    oldest = claim(sa.select(work.c.id).order_by(work.c.due).limit(1), work)
    async with engine.connect() as a, engine.connect() as b:
        await a.begin()
        assert (await a.execute(oldest)).scalar_one() == "old"
        await b.begin()
        assert (await b.execute(oldest)).scalar_one() == "new"
        await b.rollback()
        await a.rollback()


async def test_a_locked_key_holds_a_second_transaction(engine: AsyncEngine) -> None:
    async with engine.connect() as a, engine.connect() as b:
        await a.begin()
        await lock_key(a, "thread:t1")
        await b.begin()
        await b.execute(sa.text("SET LOCAL lock_timeout = '300ms'"))
        with pytest.raises(DBAPIError, match="lock timeout"):
            await lock_key(b, "thread:t1")
        await b.rollback()
        await a.commit()


async def test_an_upsert_inserts_once_and_then_updates(engine: AsyncEngine) -> None:
    async with engine.begin() as c:
        row = {"id": "u", "due": 3.0, "body": {"a": 1}, "n": 1}
        await c.execute(upsert(c, work, row, keys=["id"]))
        await c.execute(upsert(c, work, {**row, "n": 2}, keys=["id"]))
        await c.execute(insert_ignore(c, work, {**row, "n": 9}, keys=["id"]))
        rows = (await c.execute(sa.select(work.c.n, work.c.body).where(work.c.id == "u"))).all()
    assert [tuple(r) for r in rows] == [(2, {"a": 1})]


async def test_concurrent_upserts_of_one_key_leave_one_row(engine: AsyncEngine) -> None:
    async def one(n: int) -> None:
        async with engine.begin() as c:
            await c.execute(upsert(c, work, {"id": "race", "due": 1.0, "n": n}, keys=["id"]))

    await asyncio.gather(*(one(n) for n in range(8)))
    async with engine.connect() as c:
        assert (await c.execute(sa.select(sa.func.count()).where(work.c.id == "race"))).scalar_one() == 1


async def test_the_clock_reads_the_database(engine: AsyncEngine) -> None:
    async with engine.connect() as c:
        now, epoch, later = (await c.execute(sa.select(db_now(), db_epoch(), db_after(sa.literal(60.0))))).one()
    assert abs(now.timestamp() - epoch) < 1 and 59 < (later - now).total_seconds() < 61


async def test_the_tenant_lasts_for_its_transaction_only(engine: AsyncEngine) -> None:
    read = sa.select(sa.func.current_setting("app.tenant_id", True))
    async with tenant_tx(engine, "tenant-a") as c:
        assert (await c.execute(read)).scalar_one() == "tenant-a"
    async with engine.connect() as c:
        assert (await c.execute(read)).scalar_one() in (None, "")


async def test_a_search_for_brackets_matches_the_brackets_only(engine: AsyncEngine) -> None:
    # On SQL Server `[draft]` unescaped is a character class matching any one of d, r, a, f, t.
    assert "ESCAPE" in sql(sa.select(work.c.id).where(contains(work.c.id, "[d]")), MS)
    async with engine.begin() as c:
        await c.execute(work.insert(), [{"id": "[d]", "due": 3.0}, {"id": "d", "due": 4.0}])
        found = (await c.execute(sa.select(work.c.id).where(contains(work.c.id, "[d]")))).scalars().all()
    assert found == ["[d]"]
