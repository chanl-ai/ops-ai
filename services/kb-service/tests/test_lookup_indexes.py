"""The indexes a lookup by item or by source reads, on the database itself: an item's pieces and a source's links to
bases read every row of the tenant when the migration (PostgreSQL) or the golden file (SQL Server) leaves them out."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_pieces_by_item_and_links_by_source_are_indexed(engine: AsyncEngine) -> None:
    def indexes(conn: sa.Connection) -> dict[str, list[Any]]:
        found = sa.inspect(conn)
        return {
            i["name"] or "": list(i["column_names"])
            for table in ("kb_chunks", "kb_base_sources")
            for i in found.get_indexes(table)
        }

    async with engine.connect() as conn:
        seen = await conn.run_sync(indexes)
    assert seen.get("ix_kb_chunks_item") == ["tenant_id", "item_id"], seen
    assert seen.get("ix_kb_base_sources_source") == ["tenant_id", "source_id"], seen
