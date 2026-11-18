"""The files chain runs down, up, up again and down one on both databases (ops_store.testing.prove_chain)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config

from ops_store.testing import NO_SQL_SERVER, prove_chain, sql_server_schema

CHAIN = "files"
ALEMBIC_INI = str(Path(__file__).resolve().parents[1] / "alembic.ini")


@pytest.mark.postgresql_only("revisions before the SQL Server baseline are PostgreSQL history")
def test_on_postgresql(database_url: str) -> None:
    # files_0008 and the revisions before it have empty downgrades (scripts/downgrades-waiting.txt).
    prove_chain(Config(ALEMBIC_INI), CHAIN, database_url, floor="files_0008")


def test_on_sql_server_from_the_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    server, password = os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")
    with sql_server_schema(CHAIN, server, password) as url, sql_server_schema(CHAIN, server, password) as fresh:
        if url is None or fresh is None:
            pytest.skip(NO_SQL_SERVER)
        monkeypatch.setenv("OPS_DATABASE_URL", url)
        prove_chain(Config(ALEMBIC_INI), CHAIN, url, fresh=fresh)
