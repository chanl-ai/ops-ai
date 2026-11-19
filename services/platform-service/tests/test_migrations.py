"""The platform chain runs down, up, up again and down one on both databases (ops_store.testing.prove_chain)."""

from __future__ import annotations

import os

import pytest

from ops_store.testing import NO_SQL_SERVER, prove_chain, sql_server_schema

from .conftest import alembic_config

CHAIN = "platform"


@pytest.mark.postgresql_only("revisions before the SQL Server baseline are PostgreSQL history")
def test_on_postgresql_from_base(database_url: str) -> None:
    prove_chain(alembic_config(), CHAIN, database_url)


def test_on_sql_server_from_the_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    server, password = os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")
    with sql_server_schema(CHAIN, server, password) as url, sql_server_schema(CHAIN, server, password) as fresh:
        if url is None or fresh is None:
            pytest.skip(NO_SQL_SERVER)
        monkeypatch.setenv("OPS_DATABASE_URL", url)
        prove_chain(alembic_config(), CHAIN, url, fresh=fresh)
