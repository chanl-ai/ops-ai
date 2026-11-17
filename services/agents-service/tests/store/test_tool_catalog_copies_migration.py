"""Migration 0116 makes the tool catalogue copy's three tables, by failure mode: a table without its row policy holds
every tenant's rows for any reader; the down path leaves a database 0115 runs on; the upgrade cannot run again."""

from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config

from .test_drop_publish_policies import ROOT, _sql  # pyright: ignore[reportPrivateUsage]

BEFORE = "0115_workflow_list_columns"
TABLES = ("tool_catalog", "tool_catalog_operations", "tool_team_state")
POLICIES = (
    "SELECT tablename, policyname FROM pg_policies WHERE tablename IN "
    "('tool_catalog', 'tool_catalog_operations', 'tool_team_state') ORDER BY tablename"
)
HELD = "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"


def test_the_copy_tables_are_policed_and_the_migration_goes_down_and_up_again(emptied_database: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    for _ in range(2):
        command.downgrade(cfg, BEFORE)
        (gone,) = asyncio.run(_sql(emptied_database, (POLICIES, {})))
        assert gone == []
        assert asyncio.run(_sql(emptied_database, *((HELD, {"t": t}) for t in TABLES))) == [[], [], []]
        command.upgrade(cfg, "head")
        (policies,) = asyncio.run(_sql(emptied_database, (POLICIES, {})))
        assert policies == [
            ("tool_catalog", "tool_catalog_tenant"),
            ("tool_catalog_operations", "tool_catalog_operations_tenant"),
            ("tool_team_state", "tool_team_state_isolation"),
        ]
        forced = asyncio.run(_sql(emptied_database, *((HELD, {"t": t}) for t in TABLES)))
        assert forced == [[(t, True, True)] for t in TABLES]
