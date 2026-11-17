"""The agents chain runs down, up, up again and down one on both databases (ops_store.testing.prove_chain)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config

from ops_service_kit.settings import Settings
from ops_store.testing import NO_SQL_SERVER, prove_chain, sql_server_schema

CHAIN = "agents"
ALEMBIC_INI = str(Path(__file__).resolve().parents[1] / "alembic.ini")


def test_on_postgresql() -> None:
    # gateway_calls and gateway_fences, which 0006 and 0008 made, belong to tools-service's chain now
    # (tools_0001_gateway adopts them in the shared database), so going below 0008 would drop the other chain's tables.
    prove_chain(
        Config(ALEMBIC_INI),
        CHAIN,
        Settings().database_url,
        version_table="alembic_version",
        floor="0008_lease_generation",
    )


def test_on_sql_server_from_the_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    server, password = os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")
    with sql_server_schema(CHAIN, server, password) as url, sql_server_schema(CHAIN, server, password) as fresh:
        if url is None or fresh is None:
            pytest.skip(NO_SQL_SERVER)
        monkeypatch.setenv("OPS_DATABASE_URL", url)
        prove_chain(Config(ALEMBIC_INI), CHAIN, url, fresh=fresh, version_table="alembic_version")
