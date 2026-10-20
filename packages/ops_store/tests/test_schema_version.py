"""A service starts only on a database that records its chain's head (ops_store.schema_version)."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from ops_store.schema_version import check_schema

# A real chain, so head and history come from Alembic as a service's do.
CHAIN = Path(__file__).resolve().parents[3] / "services" / "models-service" / "migrations"


async def _recorded(tmp_path: Path, rows: dict[str, str]) -> str | None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'schema.db'}")
    async with engine.begin() as c:
        for table, rev in rows.items():
            await c.execute(sa.text(f"CREATE TABLE {table} (version_num VARCHAR(64) NOT NULL)"))
            await c.execute(sa.text(f"INSERT INTO {table} VALUES ('{rev}')"))
    try:
        return await check_schema(engine, CHAIN)
    finally:
        await engine.dispose()


def _revisions() -> tuple[str, str]:
    script = ScriptDirectory(str(CHAIN))
    head = script.get_current_head() or ""
    older = next(r.revision for r in script.walk_revisions() if r.revision != head)
    return head, older


async def test_a_database_at_the_head_starts(tmp_path: Path) -> None:
    head, _ = _revisions()
    assert await _recorded(tmp_path, {"alembic_version_models": head, "alembic_version": "0001_other_chain"}) is None


async def test_a_database_behind_is_refused_naming_both_revisions(tmp_path: Path) -> None:
    head, older = _revisions()
    problem = await _recorded(tmp_path, {"alembic_version_models": older})
    assert problem is not None and "behind" in problem and older in problem and head in problem


async def test_a_database_without_this_chain_is_refused(tmp_path: Path) -> None:
    problem = await _recorded(tmp_path, {"alembic_version": "0001_other_chain"})
    assert problem is not None and "none of this build's revisions" in problem
