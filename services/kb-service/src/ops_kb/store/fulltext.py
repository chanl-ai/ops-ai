"""The Postgres full-text adapter behind the Retriever port (retrieval.py)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ..retrieval import Passage

# Below half of the question's terms a passage is not an answer: "mortgage brokers selling travel insurance" shares
# two of five terms with a rate sheet and is not answered by it. With at least two terms in the question, a passage
# must also share two, so one common word ("mortgage") never carries a passage on its own.
FLOOR = 0.5
MIN_SHARED_TERMS = 2


# Every live chunk of an indexed item in a source the knowledge base reads, scored against the question's lexemes.
_SEARCH = sa.text(
    """
    WITH q AS (
        SELECT array(SELECT DISTINCT unnest(tsvector_to_array(to_tsvector('english', :question)))) AS terms
    ),
    hits AS (
        SELECT l.kb_id, c.item_id, c.version, c.title, c.section, c.page, c.text,
               (SELECT count(*) FROM unnest(q.terms) t WHERE c.tsv @@ to_tsquery('english', quote_literal(t)))
                   AS shared,
               cardinality(q.terms) AS total,
               ts_rank_cd(c.tsv, to_tsquery('english', array_to_string(
                   array(SELECT quote_literal(t) FROM unnest(q.terms) t), ' | '))) AS rank
        FROM q, kb_chunks c
        JOIN kb_items i ON i.tenant_id = c.tenant_id AND i.id = c.item_id AND i.status = 'indexed'
        JOIN kb_base_sources l ON l.tenant_id = i.tenant_id AND l.source_id = i.source_id
        WHERE c.tenant_id = :tenant AND l.kb_id = ANY(:kb_ids) AND c.withdrawn_at IS NULL
          AND cardinality(q.terms) > 0
          AND c.tsv @@ to_tsquery('english', array_to_string(
              array(SELECT quote_literal(t) FROM unnest(q.terms) t), ' | '))
    )
    SELECT * FROM hits
    WHERE shared >= LEAST(:min_shared, total) AND shared::float / total >= :floor
    ORDER BY shared::float / total DESC, rank DESC
    LIMIT :limit
    """
)


def _snippet(text: str, width: int = 280) -> str:
    return text if len(text) <= width else text[: width - 1].rsplit(" ", 1)[0] + "…"


class PostgresFullTextRetriever:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def search(self, tenant: str, kb_ids: list[str], question: str, *, limit: int) -> list[Passage]:
        if not kb_ids or not question.strip():
            return []
        params = {
            "tenant": tenant,
            "kb_ids": kb_ids,
            "question": question,
            "limit": limit,
            "floor": FLOOR,
            "min_shared": MIN_SHARED_TERMS,
        }
        async with self.engine.connect() as c:
            rows = (await c.execute(_SEARCH, params)).mappings().all()
        seen: set[tuple[str, int, str]] = set()
        out: list[Passage] = []
        for r in rows:
            # One knowledge base per passage: a chunk read by two of the asked knowledge bases is returned once.
            key = (r["item_id"], r["version"], r["text"][:64])
            if key in seen:
                continue
            seen.add(key)
            out.append(
                Passage(
                    kb_id=r["kb_id"],
                    item_id=r["item_id"],
                    version=r["version"],
                    title=r["title"],
                    section=r["section"],
                    page=r["page"],
                    text=r["text"],
                    snippet=_snippet(r["text"]),
                    score=round(float(r["shared"]) / float(r["total"]), 3),
                )
            )
        return out
