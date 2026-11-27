"""Two services migrating one PostgreSQL cluster at once, by failure mode: the second creates a role the first has made
but not yet committed. Roles are cluster-wide, so that raises a unique violation on pg_authid_rolname_index, which the
`EXCEPTION WHEN duplicate_object` in role_ddl does not catch. SQL Server has no cluster-wide roles and takes no lock."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.settings import Settings
from ops_store.schema import role_ddl, serialize_migrations

ROLE = "ops_migration_lock_probe"


async def _migrate(url: str, first: bool, held: asyncio.Event, released: asyncio.Event) -> None:
    """One service's migration: lock, create the role; the first holds its transaction open while the other starts."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as c, c.begin():
            await c.run_sync(serialize_migrations)
            await c.execute(sa.text(role_ddl(ROLE)))
            if first:
                held.set()
                await asyncio.sleep(0.5)
            else:
                released.set()
    finally:
        await engine.dispose()


async def _drop(url: str) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as c:
        await c.execute(sa.text(f"DROP ROLE IF EXISTS {ROLE}"))
    await engine.dispose()


async def test_two_migrations_creating_one_role_at_once_both_finish() -> None:
    url = Settings().database_url
    if not url.startswith("postgresql"):
        pytest.skip("cluster-wide roles are PostgreSQL's")
    await _drop(url)
    held, released = asyncio.Event(), asyncio.Event()
    try:
        first = asyncio.create_task(_migrate(url, True, held, released))
        await held.wait()
        second = asyncio.create_task(_migrate(url, False, held, released))
        await asyncio.gather(first, second)
        engine = create_async_engine(url)
        async with engine.connect() as c:
            found = (await c.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": ROLE})).first()
        await engine.dispose()
        assert found is not None
    finally:
        await _drop(url)


def test_a_connection_that_is_not_postgresql_takes_no_lock() -> None:
    class Fake:
        class dialect:  # noqa: N801 - mirrors the attribute SQLAlchemy exposes
            name = "mssql"

        def execute(self, *a: object, **k: object) -> None:
            raise AssertionError("SQL Server has no cluster-wide roles; nothing to lock")

    serialize_migrations(Fake())  # type: ignore[arg-type]
