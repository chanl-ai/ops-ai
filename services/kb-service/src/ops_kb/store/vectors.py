"""The built-in vector store behind the VectorStore port (retrieval.py): pgvector in the service's own PostgreSQL.
Units without a vector of the environment's model and width are listed for embedding; a search compares the question's
vector with each unit's by cosine distance (ops_store.dialect) and returns each piece once by its nearest unit."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import isolation
from ops_store.dialect import vector_distance_sql, vector_text
from ops_store.team_scope import team_visible

from .knowledge import ROLE, kb_chunks, kb_unit_vectors, kb_units

# Units read per piece asked for, as the keyword lane reads them: a piece's text, children and questions can all be
# near, and each piece is returned once.
OVERFETCH = 4


def _search_sql(width: int) -> sa.TextClause:
    distance = vector_distance_sql("postgresql", "v.embedding", "query", width)
    return sa.text(
        f"""
        SELECT l.kb_id, c.id AS chunk_id, c.item_id, c.version, c.title, c.section, c.page, c.text,
               u.kind AS unit_kind, u.text AS unit_text, i.file_id, i.url, i.verified,
               1 - {distance} AS similarity
        FROM kb_unit_vectors v
        JOIN kb_units u ON u.tenant_id = v.tenant_id AND u.id = v.unit_id
        JOIN kb_chunks c ON c.tenant_id = u.tenant_id AND c.id = u.chunk_id AND c.withdrawn_at IS NULL
        JOIN kb_items i ON i.tenant_id = c.tenant_id AND i.id = c.item_id AND i.status = 'indexed'
             AND i.duplicate_of IS NULL
        JOIN kb_base_sources l ON l.tenant_id = i.tenant_id AND l.source_id = i.source_id
        WHERE v.tenant_id = :tenant AND l.kb_id = ANY(:kb_ids) AND v.model = :model AND v.width = :width
        ORDER BY {distance}
        LIMIT :limit
        """
    )


class PgVectorStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._ready: bool | None = None

    async def ready(self) -> bool:
        """Whether this database has the vector table (pgvector installed when the chain ran)."""
        if self._ready is None:
            async with self.engine.connect() as c:
                if c.dialect.name != "postgresql":
                    self._ready = False
                else:
                    found = await c.scalar(sa.text("SELECT to_regclass('kb_unit_vectors')"))
                    self._ready = found is not None
        return self._ready

    async def pending(self, tenant: str, *, model: str, width: int, limit: int) -> list[dict[str, Any]]:
        """Units of live pieces with no vector of `model` at `width`, oldest piece first."""
        u, c, v = kb_units, kb_chunks, kb_unit_vectors
        current = sa.and_(v.c.tenant_id == u.c.tenant_id, v.c.unit_id == u.c.id, v.c.model == model, v.c.width == width)
        q = (
            sa.select(u.c.id, u.c.chunk_id, u.c.item_id, u.c.heading, u.c.text)
            .join(c, (c.c.tenant_id == u.c.tenant_id) & (c.c.id == u.c.chunk_id))
            .where(
                u.c.tenant_id == tenant,
                c.c.withdrawn_at.is_(None),
                ~sa.exists().where(current),
                team_visible(u),
                team_visible(c),
            )
            .order_by(u.c.chunk_id, u.c.position)
            .limit(limit)
        )
        async with isolation.isolated_tx(self.engine, role=ROLE) as conn:
            return [dict(r) for r in (await conn.execute(q)).mappings()]

    async def pending_count(self, tenant: str, *, model: str, width: int) -> int:
        """How many units of live pieces have no vector of `model` at `width`."""
        u, c, v = kb_units, kb_chunks, kb_unit_vectors
        current = sa.and_(v.c.tenant_id == u.c.tenant_id, v.c.unit_id == u.c.id, v.c.model == model, v.c.width == width)
        q = (
            sa.select(sa.func.count())
            .select_from(u.join(c, (c.c.tenant_id == u.c.tenant_id) & (c.c.id == u.c.chunk_id)))
            .where(
                u.c.tenant_id == tenant,
                c.c.withdrawn_at.is_(None),
                ~sa.exists().where(current),
                team_visible(u),
                team_visible(c),
            )
        )
        async with isolation.isolated_tx(self.engine, role=ROLE) as conn:
            return int(await conn.scalar(q) or 0)

    async def put(self, tenant: str, rows: list[dict[str, Any]], *, model: str, width: int) -> None:
        """Each unit's vector, replacing one of another model or width."""
        if not rows:
            return
        v = kb_unit_vectors
        now = datetime.now(UTC)
        async with isolation.isolated_tx(self.engine, role=ROLE) as conn:
            ids = [str(r["unit_id"]) for r in rows]
            teams = {
                str(r[0]): str(r[1])
                for r in await conn.execute(
                    sa.select(kb_units.c.id, kb_units.c.team_id).where(
                        kb_units.c.tenant_id == tenant, kb_units.c.id.in_(ids), team_visible(kb_units)
                    )
                )
            }
            await conn.execute(sa.delete(v).where(v.c.tenant_id == tenant, v.c.unit_id.in_(ids), team_visible(v)))
            await conn.execute(
                sa.insert(v),
                [
                    {
                        "tenant_id": tenant,
                        "team_id": teams[str(r["unit_id"])],
                        "unit_id": r["unit_id"],
                        "chunk_id": r["chunk_id"],
                        "item_id": r["item_id"],
                        "model": model,
                        "width": width,
                        "embedding": vector_text(r["vector"]),
                        "embedded_at": now,
                    }
                    for r in rows
                    if str(r["unit_id"]) in teams
                ],
            )

    async def coverage(self, tenant: str, kb_ids: list[str], *, model: str, width: int) -> tuple[int, int]:
        """(units with a current vector, units of live pieces) in the bases."""
        q = sa.text(
            """
            SELECT count(DISTINCT u.id) AS total,
                   count(DISTINCT v.unit_id) FILTER (WHERE v.model = :model AND v.width = :width) AS embedded
            FROM kb_units u
            JOIN kb_chunks c ON c.tenant_id = u.tenant_id AND c.id = u.chunk_id AND c.withdrawn_at IS NULL
            JOIN kb_items i ON i.tenant_id = c.tenant_id AND i.id = c.item_id AND i.status = 'indexed'
            JOIN kb_base_sources l ON l.tenant_id = i.tenant_id AND l.source_id = i.source_id
            LEFT JOIN kb_unit_vectors v ON v.tenant_id = u.tenant_id AND v.unit_id = u.id
            WHERE u.tenant_id = :tenant AND l.kb_id = ANY(:kb_ids)
            """
        )
        params = {"tenant": tenant, "kb_ids": kb_ids, "model": model, "width": width}
        async with isolation.isolated_tx(self.engine, role=ROLE) as conn:
            row = (await conn.execute(q, params)).mappings().one()
        return int(row["embedded"] or 0), int(row["total"] or 0)

    async def nearest(
        self, tenant: str, kb_ids: list[str], query: list[float], *, model: str, width: int, limit: int
    ) -> list[dict[str, Any]]:
        """The units nearest the question's vector, with their piece and similarity (1 is the same direction)."""
        params = {
            "tenant": tenant,
            "kb_ids": kb_ids,
            "query": vector_text(query),
            "model": model,
            "width": width,
            "limit": limit * OVERFETCH,
        }
        async with isolation.isolated_tx(self.engine, role=ROLE) as conn:
            return [dict(r) for r in (await conn.execute(_search_sql(width), params)).mappings()]
