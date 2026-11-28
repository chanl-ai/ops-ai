"""`role_ddl` where two databases migrate at once on one PostgreSQL server: roles are server-wide, so a second session
creating a role while the first's CREATE ROLE is uncommitted gets a unique violation on pg_authid_rolname_index, in
whichever database it runs. The statement must leave the role made and raise nothing. SQL Server has none."""

from __future__ import annotations

import asyncio
import secrets

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_service_kit.settings import Settings
from ops_store.schema import role_ddl

ROLE = "ops_role_ddl_probe"


async def _blocked_on_a_lock(admin: AsyncEngine, database: str) -> None:
    """Returns once a session on `database` waits for another transaction, so the two creations truly overlap."""
    async with admin.connect() as c:
        for _ in range(200):
            waiting = await c.scalar(
                sa.text("SELECT count(*) FROM pg_stat_activity WHERE datname = :d AND wait_event_type = 'Lock'"),
                {"d": database},
            )
            if waiting:
                return
            await asyncio.sleep(0.05)
    raise AssertionError(f"no session on {database} ever waited on the first role creation")


async def test_two_databases_creating_one_role_at_once_leave_it_made() -> None:
    url = make_url(Settings().database_url)
    if url.get_backend_name() != "postgresql":
        pytest.skip("server-wide roles are PostgreSQL's")
    tag = secrets.token_hex(3)
    names = (f"ops_roledd_a_{tag}", f"ops_roledd_b_{tag}")
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    engines: list[AsyncEngine] = []
    try:
        async with admin.connect() as c:
            await c.execute(sa.text(f"DROP ROLE IF EXISTS {ROLE}"))
            for n in names:
                await c.execute(sa.text(f'CREATE DATABASE "{n}"'))
        engines = [create_async_engine(url.set(database=n)) for n in names]
        first_made = asyncio.Event()
        first_may_commit = asyncio.Event()

        async def first() -> None:
            async with engines[0].connect() as c, c.begin():
                await c.execute(sa.text(role_ddl(ROLE)))
                first_made.set()
                await first_may_commit.wait()

        async def second() -> None:
            await first_made.wait()
            async with engines[1].connect() as c, c.begin():
                await c.execute(sa.text(role_ddl(ROLE)))

        a, b = asyncio.create_task(first()), asyncio.create_task(second())
        await first_made.wait()
        await _blocked_on_a_lock(admin, names[1])
        first_may_commit.set()
        await asyncio.gather(a, b)
        async with admin.connect() as c:
            assert await c.scalar(sa.text("SELECT count(*) FROM pg_roles WHERE rolname = :r"), {"r": ROLE}) == 1
    finally:
        for e in engines:
            await e.dispose()
        async with admin.connect() as c:
            for n in names:
                await c.execute(sa.text(f'DROP DATABASE IF EXISTS "{n}" WITH (FORCE)'))
            await c.execute(sa.text(f"DROP ROLE IF EXISTS {ROLE}"))
        await admin.dispose()
