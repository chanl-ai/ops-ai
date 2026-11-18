"""kb's row filters and its system user, on both databases, by failure mode: a kb table left with no row filter after
kb_0026 or after its downgrade (the predicate functions are made again under policies that are dropped and made
again), the predicates naming kb's system user at a revision that should not or not naming it at one that should,
and the system user reading a kb table it was never granted, so a broad grant added later would widen what it reads
across tenants without any test noticing."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_kb.store.knowledge import SYSTEM_ROLE
from ops_store import isolation

ROOT = Path(__file__).parents[1]
CONFIG = str(ROOT / "alembic.ini")
REASON = "test: kb's system user reads only the tables it was granted"
# Every kb table a row filter guards on both databases (kb_0011, kb_0014, kb_0016).
GUARDED = frozenset(
    {
        "kb_bases",
        "kb_sources",
        "kb_base_sources",
        "kb_items",
        "kb_item_versions",
        "kb_chunks",
        "kb_changes",
        "kb_runs",
        "kb_retired_bases",
        "kb_units",
        "kb_outbox",
    }
)

MSSQL_FILTERED = sa.text(
    "SELECT OBJECT_NAME(sp.target_object_id) AS t FROM sys.security_predicates sp "
    "JOIN sys.security_policies p ON p.object_id = sp.object_id "
    "WHERE p.is_enabled = 1 AND sp.predicate_type = 0"
)
MSSQL_NAMES_SYSTEM = sa.text(
    "SELECT COUNT(*) FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id "
    "WHERE s.name = N'ops_security' AND o.name LIKE N'kb[_]%' "
    "AND OBJECT_DEFINITION(o.object_id) LIKE N'%ops_kb_system%'"
)
PG_FILTERED = sa.text(
    "SELECT c.relname AS t FROM pg_class c WHERE c.relrowsecurity "
    "AND EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = c.relname)"
)


def _state(url: str) -> tuple[set[str], int | None]:
    """The kb tables an enabled row filter guards, and on SQL Server how many kb predicate functions name the system
    user (None on PostgreSQL, whose system role bypasses row security instead)."""

    async def read() -> tuple[set[str], int | None]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as c:
                if c.dialect.name == "mssql":
                    filtered = {str(r[0]) for r in await c.execute(MSSQL_FILTERED)}
                    return filtered & GUARDED, int((await c.execute(MSSQL_NAMES_SYSTEM)).scalar_one())
                return {str(r[0]) for r in await c.execute(PG_FILTERED)} & GUARDED, None
        finally:
            await engine.dispose()

    return asyncio.run(read())


def test_every_kb_table_keeps_its_row_filter_across_kb_0026_and_back(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The chain runs against the database this case is on: env.py reads the address from Settings.
    monkeypatch.setenv("OPS_DATABASE_URL", database_url)
    mssql = database_url.startswith("mssql")
    filtered, naming = _state(database_url)
    assert filtered == GUARDED, GUARDED - filtered
    assert naming == (4 if mssql else None)
    try:
        command.downgrade(Config(CONFIG), "kb_0025")
        filtered, naming = _state(database_url)
        assert filtered == GUARDED, GUARDED - filtered
        assert naming == (0 if mssql else None)
    finally:
        command.upgrade(Config(CONFIG), "head")
    filtered, naming = _state(database_url)
    assert filtered == GUARDED, GUARDED - filtered
    assert naming == (4 if mssql else None)


async def test_the_system_user_reads_sources_and_is_refused_items_and_chunks(engine: AsyncEngine) -> None:
    async with isolation.system_tx(engine, REASON, role=SYSTEM_ROLE) as c:
        await c.execute(sa.text("SELECT COUNT(*) FROM kb_sources"))
    for table in ("kb_items", "kb_chunks"):
        with pytest.raises(DBAPIError):
            async with isolation.system_tx(engine, REASON, role=SYSTEM_ROLE) as c:
                await c.execute(sa.select(sa.func.count()).select_from(sa.table(table)))
