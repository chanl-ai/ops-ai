"""Migration kb_0010 (c-507) makes a knowledge base's and a source's team required, by failure mode: a row with no team
survives the migration and every team reads it; the refusal names nothing, so the operator cannot place it."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
BEFORE = "kb_0009"


async def _sql(url: str, *statements: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as c:
        for text in statements:
            await c.execute(sa.text(text))
    await engine.dispose()


def test_a_base_with_no_team_is_refused_by_name_until_placed(database_url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    insert = (
        "INSERT INTO kb_bases (tenant_id, id, team_id, name, slug, description, color, owner, collections, retrieval, "
        "created_by, created_at) VALUES ('t_kb0010', 'kb_orphan', NULL, 'Orphan', 'orphan', '', 'gray', 'o@x', "
        "CAST('[]' AS json), CAST('{}' AS json), 'o@x', now())"
    )
    asyncio.run(_sql(database_url, insert))
    try:
        with pytest.raises(RuntimeError, match="kb_bases kb_orphan of t_kb0010"):
            command.upgrade(cfg, "head")
    finally:
        asyncio.run(_sql(database_url, "DELETE FROM kb_bases WHERE tenant_id = 't_kb0010'"))
        command.upgrade(cfg, "head")
