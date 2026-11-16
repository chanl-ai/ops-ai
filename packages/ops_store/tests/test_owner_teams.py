"""`Store.owner_teams` and `isolation.tenant_wide_on` on a caller's own connection, outside a request, on each database,
by failure mode: an owner read that misses another team's row, one that checks out a second connection beside the
caller's, one that leaves the caller's connection reading every team afterwards, also when the block raises, and one
that answers another tenant's owner where only the code's predicate can stop it (a table with no policy yet). Also
`team_visible` on a child of a parent keyed (tenant_id, id): a parent id two tenants hold must not let one tenant's
visible parent show the other tenant's child. Inside a request the same call is covered by ops_identity's
tests/test_request_transaction.py."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects import mssql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.backends import backends
from ops_store.conformance import engine_for, sql_server_database
from ops_store.database import open_database
from ops_store.schema import (
    MSSQL_SECURITY,
    TEAM_OWNED,
    TENANT_SCOPED,
    isolation_ddl,
    isolation_drop_ddl,
    role_ddl,
    security_ddl,
    team_owned_via,
)
from ops_store.store import Store
from ops_store.team_scope import acting_as, team_visible

SQL_SERVER = (os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD"))
ROLE = "ops_owner_teams_test"
CHAIN = "storetestowners"
OWNER = "the owning team a refusal is decided on"

meta = sa.MetaData()
items = sa.Table(
    "store_test_owner_items",
    meta,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)
# No policy on either, as on a table whose policy has not landed: only the statement's own predicates filter.
parents = sa.Table(
    "store_test_owner_parents",
    meta,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    info=TEAM_OWNED,
)
children = sa.Table(
    "store_test_owner_children",
    meta,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("parent_id", sa.String(64), primary_key=True),
    info=team_owned_via("store_test_owner_parents", "parent_id"),
)


class Items(Store):
    # A role row security applies to: the compose superuser bypasses it, as no runtime login does.
    role = ROLE


def _mssql_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


async def _drop(c: Any, dialect: str) -> None:
    if dialect == "mssql":
        for statement in isolation_drop_ddl(items, "mssql"):
            await c.execute(sa.text(statement))
        for part in ("read", "write"):
            fn = f"{MSSQL_SECURITY}.{CHAIN}_team_{part}"
            await c.execute(sa.text(f"IF OBJECT_ID(N'{fn}', N'IF') IS NOT NULL DROP FUNCTION {fn}"))
    await c.run_sync(meta.drop_all)


@pytest.fixture(params=["postgresql", "mssql"])
async def engine(request: pytest.FixtureRequest) -> AsyncIterator[AsyncEngine]:
    with sql_server_database("ops_owners", *SQL_SERVER) as mssql_url:
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
            await c.execute(
                items.insert(),
                [
                    {"id": "mine", "tenant_id": "t1", "team_id": "a"},
                    {"id": "theirs", "tenant_id": "t1", "team_id": "b"},
                    {"id": "elsewhere", "tenant_id": "t2", "team_id": "a"},
                ],
            )
            await c.execute(
                parents.insert(),
                [
                    {"tenant_id": "t1", "id": "shared", "team_id": "a"},
                    {"tenant_id": "t2", "id": "shared", "team_id": "b"},
                    {"tenant_id": "t2", "id": "only_t2", "team_id": "b"},
                ],
            )
            await c.execute(children.insert(), [{"tenant_id": "t2", "parent_id": "shared"}])
            if request.param == "postgresql":
                await c.execute(sa.text(role_ddl(ROLE)))
                for t in (items, parents, children):
                    await c.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t.name} TO {ROLE}"))
                for statement in isolation_ddl(items, "postgresql"):
                    await c.execute(sa.text(statement))
            else:
                for statement in security_ddl(CHAIN, [items], column_type=_mssql_type, system_user=None):
                    await c.execute(sa.text(statement))
        yield e
        async with e.begin() as c:
            await _drop(c, request.param)
        await e.dispose()


async def _ids(conn: AsyncConnection) -> list[str]:
    return [str(i) for i in (await conn.execute(sa.select(items.c.id).order_by(items.c.id))).scalars()]


async def test_a_passed_connection_answers_the_owner_of_every_team_in_its_tenant(engine: AsyncEngine) -> None:
    st = Items(engine)
    with isolation.scope("t1", "a"):
        async with st.tx() as conn:
            owners = await st.owner_teams(conn, items, {"mine", "theirs", "elsewhere"}, OWNER)
    assert owners == {"mine": "a", "theirs": "b"}


async def test_a_passed_connection_is_the_only_one_checked_out(engine: AsyncEngine) -> None:
    st = Items(engine)
    checkouts: list[object] = []

    def checked_out(dbapi_conn: object, *_: object) -> None:
        checkouts.append(dbapi_conn)

    event.listen(engine.sync_engine.pool, "checkout", checked_out)
    try:
        with isolation.scope("t1", "a"):
            async with st.tx() as conn:
                await st.owner_teams(conn, items, {"theirs"}, OWNER)
    finally:
        event.remove(engine.sync_engine.pool, "checkout", checked_out)
    assert len(checkouts) == 1, f"{len(checkouts)} checkouts for one transaction"


async def test_the_passed_connection_reads_as_its_team_after_the_owner_read(engine: AsyncEngine) -> None:
    st = Items(engine)
    with isolation.scope("t1", "a"):
        async with st.tx() as conn:
            assert await _ids(conn) == ["mine"]
            await st.owner_teams(conn, items, {"theirs"}, OWNER)
            assert await _ids(conn) == ["mine"]


async def test_a_block_that_raises_still_gives_the_connection_its_team_back(engine: AsyncEngine) -> None:
    with isolation.scope("t1", "a"):
        async with Items(engine).tx() as conn:
            with pytest.raises(LookupError):
                async with isolation.tenant_wide_on(conn, OWNER) as wide:
                    assert await _ids(wide) == ["mine", "theirs"]
                    raise LookupError("refused after the wide read")
            assert await _ids(conn) == ["mine"]


async def test_an_owner_read_names_the_callers_tenant_where_no_policy_does(engine: AsyncEngine) -> None:
    st = Items(engine)
    with isolation.scope("t1", "a"):
        async with st.tx() as conn:
            owners = await st.owner_teams(conn, parents, {"shared", "only_t2"}, OWNER)
    assert owners == {"shared": "a"}


async def test_a_child_follows_its_own_tenants_parent_not_one_holding_the_same_id(engine: AsyncEngine) -> None:
    with isolation.scope("t2", "a"), acting_as("a"):
        async with Items(engine).tx() as conn:
            q = sa.select(children.c.parent_id).where(children.c.tenant_id == "t2", team_visible(children))
            assert (await conn.execute(q)).all() == []
