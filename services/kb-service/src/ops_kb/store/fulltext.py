"""The Postgres full-text adapter behind the Retriever port (retrieval.py)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import isolation

from ..retrieval import Passage
from .knowledge import ROLE

# Below half of the question's terms a passage is not an answer: "mortgage brokers selling travel insurance" shares
# two of five terms with a rate sheet and is not answered by it. With at least two terms in the question, a passage
# must also share two, so one common word ("mortgage") never carries a passage on its own. A long prompt (a workflow
# agent step with its instructions) is scored against a bounded term set, or the answering passage falls under the
# floor because the extra words drown it.
FLOOR = 0.5
MIN_SHARED_TERMS = 2
TERM_CAP = 6


# Every index unit of a live piece of an indexed item in a source the knowledge base reads, scored against the
# question's lexemes. A piece is returned by its best unit (its own text, a child, a question).
_SEARCH = sa.text(
    """
    WITH q AS (
        SELECT array(SELECT DISTINCT unnest(tsvector_to_array(to_tsvector('english', :question)))) AS terms
    ),
    hits AS (
        SELECT l.kb_id, c.id AS chunk_id, c.item_id, c.version, c.title, c.section, c.page, c.text,
               u.kind AS unit_kind, u.text AS unit_text,
               (SELECT count(*) FROM unnest(q.terms) t WHERE u.tsv @@ to_tsquery('english', quote_literal(t)))
                   AS shared,
               cardinality(q.terms) AS total,
               ts_rank_cd(u.tsv, to_tsquery('english', array_to_string(
                   array(SELECT quote_literal(t) FROM unnest(q.terms) t), ' | '))) AS rank
        FROM q, kb_units u
        JOIN kb_chunks c ON c.tenant_id = u.tenant_id AND c.id = u.chunk_id AND c.withdrawn_at IS NULL
        JOIN kb_items i ON i.tenant_id = c.tenant_id AND i.id = c.item_id AND i.status = 'indexed'
        JOIN kb_base_sources l ON l.tenant_id = i.tenant_id AND l.source_id = i.source_id
        WHERE u.tenant_id = :tenant AND l.kb_id = ANY(:kb_ids)
          AND cardinality(q.terms) > 0
          AND u.tsv @@ to_tsquery('english', array_to_string(
              array(SELECT quote_literal(t) FROM unnest(q.terms) t), ' | '))
    )
    SELECT * FROM hits
    WHERE shared >= LEAST(:min_shared, total)
      AND shared::float / LEAST(total, :term_cap) >= :floor
    ORDER BY shared::float / LEAST(total, :term_cap) DESC, rank DESC
    LIMIT :limit
    """
)
# Units read per piece asked for: a piece's own text, a child and a question can all match, and each piece is
# returned once.
OVERFETCH = 4
# At most this many pieces from one document, so one long document never fills every passage.
PER_ITEM = 2


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
            "limit": limit * OVERFETCH,
            "floor": FLOOR,
            "min_shared": MIN_SHARED_TERMS,
            "term_cap": TERM_CAP,
        }
        # As the tenant role, so the team policy keeps another team's chunks out of the search.
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            rows = (await c.execute(_SEARCH, params)).mappings().all()
        seen: set[str] = set()
        per_item: dict[str, int] = {}
        out: list[Passage] = []
        for r in rows:
            # One passage per piece, by its best unit: a piece read by two of the asked knowledge bases, or matched by
            # its text and a question, is returned once.
            if r["chunk_id"] in seen or per_item.get(r["item_id"], 0) >= PER_ITEM:
                continue
            seen.add(r["chunk_id"])
            per_item[r["item_id"]] = per_item.get(r["item_id"], 0) + 1
            if len(out) == limit:
                break
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
                    matched=r["unit_kind"],
                    matched_text=r["unit_text"],
                )
            )
        return out
