"""The platform chain migrates up from nothing and back down, in its own version table, beside the other services'; on
SQL Server from its baseline (revisions before it are PostgreSQL history that never renders there), on a database the
golden DDL installed. Synchronous: Alembic's environment runs its own event loop."""

from __future__ import annotations

import asyncio
import os

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from ops_platform.store.tables import metadata
from ops_store.schema import isolated_tables
from ops_store.testing import NO_SQL_SERVER, sql_server_schema

from .conftest import alembic_config

HEAD = "0044_signin_sp_portable_body"
# Where the chain's portable revisions begin: `BASELINE["platform"]` in deploy/database/mssql.py.
SQL_SERVER_BASELINE = "0026_workspace_owner"


async def tables_and_version(url: str) -> tuple[set[str], str | None]:
    engine = create_async_engine(url)
    async with engine.connect() as c:
        names = set(await c.run_sync(lambda s: sa.inspect(s).get_table_names()))
        version = None
        if "alembic_version_platform" in names:
            version = (await c.execute(sa.text("select version_num from alembic_version_platform"))).scalar()
    await engine.dispose()
    return names, version


@pytest.mark.postgresql_only("revisions before the SQL Server baseline are PostgreSQL history")
def test_down_to_base_and_up_to_head(database_url: str) -> None:
    ours = set(metadata.tables)
    command.downgrade(alembic_config(), "base")
    names, version = asyncio.run(tables_and_version(database_url))
    assert not ours & names and version is None
    command.upgrade(alembic_config(), "head")
    names, version = asyncio.run(tables_and_version(database_url))
    assert ours <= names and version == HEAD


def shape(c: sa.Connection) -> set[tuple[object, ...]]:
    """What a schema holds, as SQL Server reflects it, one tuple per fact: each platform table's columns, indexes (a
    unique constraint's among them), keys and security policy, and the chain's version. ops_store.schema.differences
    needs CHECK and unique-constraint reflection, which SQLAlchemy's SQL Server dialect lacks."""
    i = sa.inspect(c)
    out: set[tuple[object, ...]] = {
        ("version", c.execute(sa.text("select version_num from alembic_version_platform")).scalar())
    }
    for t in sorted(set(i.get_table_names()) & set(metadata.tables)):
        out |= {(t, x["name"], str(x["type"]), x["nullable"], x.get("default") is not None) for x in i.get_columns(t)}
        out |= {
            (t, "index", x["name"], tuple(x["column_names"]), bool(x["unique"]), str(x.get("dialect_options", {})))
            for x in i.get_indexes(t)
        }
        out |= {
            (
                t,
                "key",
                x["name"],
                tuple(x["constrained_columns"]),
                tuple(x["referred_columns"]),
                x.get("options", {}).get("ondelete"),
            )
            for x in i.get_foreign_keys(t)
        }
    out |= {("policy", t, kind) for t, kind in isolated_tables(c).items() if t in metadata.tables}
    return out


async def read_shape(url: str) -> set[tuple[object, ...]]:
    engine = create_async_engine(url)
    async with engine.connect() as c:
        found = await c.run_sync(shape)
    await engine.dispose()
    return found


def test_on_sql_server_down_to_the_baseline_up_again_and_rerun(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every portable revision's downgrade and upgrade run on a live SQL Server, a second upgrade is a no-op, down one
    and up again, and the database then holds what a fresh install of the golden DDL holds, policies included."""
    server, password = os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")
    with (
        sql_server_schema("platform", server, password) as url,
        sql_server_schema("platform", server, password) as fresh,
    ):
        if url is None or fresh is None:
            pytest.skip(NO_SQL_SERVER)
        monkeypatch.setenv("OPS_DATABASE_URL", url)
        config = alembic_config()
        command.downgrade(config, SQL_SERVER_BASELINE)
        assert ("version", SQL_SERVER_BASELINE) in asyncio.run(read_shape(url))
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        command.downgrade(config, "-1")
        command.upgrade(config, "head")
        moved, installed = asyncio.run(read_shape(url)), asyncio.run(read_shape(fresh))
        assert ("version", HEAD) in installed
        assert (sorted(moved - installed, key=str), sorted(installed - moved, key=str)) == ([], [])
