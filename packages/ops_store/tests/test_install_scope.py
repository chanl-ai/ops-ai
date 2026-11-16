"""`Store.install_tx(reason)` on each database, by failure mode: an install-wide statement that reads or writes a
tenant table's rows, one that opens a second connection inside a request, one that leaves the request's connection in
its scope afterwards, and the guard on `Store.tx()` loosened by it."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects import mssql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.backends import backends
from ops_store.conformance import engine_for, sql_server_database
from ops_store.database import open_database
from ops_store.dialect import dialect_of
from ops_store.isolation import NoTenantError
from ops_store.schema import (
    MSSQL_SECURITY,
    TENANT_SCOPED,
    isolation_ddl,
    isolation_drop_ddl,
    role_ddl,
    security_ddl,
    system,
)
from ops_store.store import Store

SQL_SERVER = (os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD"))
ROLE = "ops_install_scope_test"
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


class Install(Store):
    # A role row security applies to: the compose superuser bypasses it, as no runtime login does.
    role = ROLE

    async def setting(self, name: str) -> str | None:
        async with self.install_tx(SETTINGS) as c:
            return await c.scalar(sa.select(settings.c.value).where(settings.c.name == name))

    async def note_ids(self) -> list[str]:
        async with self.tx() as c:
            return [str(i) for i in (await c.execute(sa.select(notes.c.id).order_by(notes.c.id))).scalars()]


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
            if request.param == "postgresql":
                await c.execute(sa.text(role_ddl(ROLE)))
                for t in (settings, notes):
                    await c.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t.name} TO {ROLE}"))
                for statement in isolation_ddl(notes, "postgresql"):
                    await c.execute(sa.text(statement))
            else:
                for statement in security_ddl(CHAIN, [notes], column_type=_mssql_type, system_user=None):
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
        assert list((await c.execute(sa.select(notes.c.id))).scalars()) == []
        with pytest.raises(NoTenantError):
            isolation.tenant()
    with pytest.raises(DBAPIError):
        async with st.install_tx(SETTINGS) as c:
            # The empty tenant no context can carry: refused by the write check, not stored where none can read it.
            await c.execute(notes.insert().values(id="n3", tenant_id=""))
    with pytest.raises(NoTenantError):
        await st.note_ids()


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
                        hidden = list((await c.execute(sa.select(notes.c.id))).scalars())
                    # The block around it reads on as the caller, with no statement of its own to set that again.
                    restored = list((await outer.execute(sa.select(notes.c.id))).scalars())
                after = await st.note_ids()
    finally:
        event.remove(engine.sync_engine.pool, "checkout", checked_out)
    assert (before, region, hidden, restored, after) == (["n1"], "eu", [], ["n1"], ["n1"])
    assert len(checkouts) == 1, f"{len(checkouts)} checkouts in one request on {dialect_of(engine)}"
