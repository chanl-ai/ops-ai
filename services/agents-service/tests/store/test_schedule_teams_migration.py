"""Migration 20261126_1200 makes workflow_schedules team-owned, by failure mode: its down path brings back a policy
other than the one 20261123_1900 made (another rule, or none), or one that a later step down cannot get past, as a
schema-bound SQL Server policy refuses DROP TABLE. On the PostgreSQL test database and on a scratch SQL Server one
holding the golden DDL."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from ops_store.testing import NO_SQL_SERVER, schema_shape, sql_server_schema

ROOT = Path(__file__).resolve().parents[2]
BELOW = "20261124_0257_skill_owner_ids"  # before workflow_schedules existed
BEFORE = "20261124_2313_agent_instruction"


def _round_trip(url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    tables = {"workflow_schedules"}
    try:
        command.downgrade(cfg, BELOW)
        command.upgrade(cfg, BEFORE)
        made = schema_shape(url, tables)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, BEFORE)
        back = schema_shape(url, tables)
        assert sorted(made ^ back, key=str) == [], "the down path changed what 20261123_1900 made"
        assert any(f[0] == "policy" for f in made), f"20261123_1900 left workflow_schedules unpoliced: {made}"
        command.downgrade(cfg, BELOW)
    finally:
        command.upgrade(cfg, "head")


def test_on_postgresql(emptied_database: str) -> None:
    _round_trip(emptied_database)


def test_on_sql_server(monkeypatch: pytest.MonkeyPatch) -> None:
    server, password = os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")
    with sql_server_schema("agents", server, password) as url:
        if url is None:
            pytest.skip(NO_SQL_SERVER)
        monkeypatch.setenv("OPS_DATABASE_URL", url)
        _round_trip(url)
