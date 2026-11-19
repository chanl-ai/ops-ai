"""dialect.system_tx on each database, by failure mode: a system transaction counted as two (SQL Server's REVERT run
after the commit begins a second one), and an impersonation left on the pooled connection when the block fails, so the
next checkout reads as the system user."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import nullcontext
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.settings import Settings
from ops_store.backends import backends
from ops_store.conformance import engine_for, sql_server_database
from ops_store.database import open_database
from ops_store.dialect import dialect_of, system_tx

SQL_SERVER = (os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD"))
SYSTEM_USER = "ops_store_test_system"


@pytest.fixture(params=["postgresql", "mssql"])
async def engine(request: pytest.FixtureRequest) -> AsyncIterator[AsyncEngine]:
    with sql_server_database("ops_system_tx", *SQL_SERVER) as mssql:
        if request.param == "mssql":
            if mssql is None:
                pytest.skip("set OPS_MSSQL_SERVER and MSSQL_SA_PASSWORD to run on SQL Server")
            url = mssql
        else:
            (backend,) = backends(Settings().database_url)
            await (await engine_for(backend)).dispose()
            url = backend.url
        # One pooled connection, so the checkout after a block is the connection the block used.
        e = open_database(url, pool_size=1, max_overflow=0)
        if request.param == "mssql":
            async with e.begin() as c:
                await c.execute(sa.text(f"CREATE USER {SYSTEM_USER} WITHOUT LOGIN"))
        yield e
        await e.dispose()


async def test_a_system_transaction_is_one_transaction_and_leaves_no_impersonation(engine: AsyncEngine) -> None:
    began: list[Any] = []
    event.listen(engine.sync_engine, "begin", began.append)
    async with engine.connect() as c:
        mssql = dialect_of(c) == "mssql"
        me = sa.text("SELECT USER_NAME()" if mssql else "SELECT current_user")
        login = (await c.execute(me)).scalar_one()
        await c.rollback()
    role = SYSTEM_USER if mssql else None
    for fails in (False, True):
        began.clear()
        with pytest.raises(RuntimeError) if fails else nullcontext():
            async with system_tx(engine, role=role) as c:
                assert (await c.execute(me)).scalar_one() == (SYSTEM_USER if mssql else login)
                if fails:
                    raise RuntimeError("the block failed")
        if not fails:
            assert len(began) == 1, f"{len(began)} transactions for one system block"
        async with engine.connect() as c:
            assert (await c.execute(me)).scalar_one() == login, f"still impersonating after the block (fails={fails})"
            await c.rollback()
