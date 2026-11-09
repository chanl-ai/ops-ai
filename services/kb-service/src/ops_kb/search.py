"""HybridRetriever: the keyword and meaning lanes behind the Retriever port (retrieval.py), on the service's own
PostgreSQL. The meaning lane runs when this stack has an embedding model and the bases' units have vectors of it; when
it cannot, the result says why and the keyword lane answers alone."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from .embedding import Embedder, EmbedFailed
from .retrieval import Found, Lane, Search, fuse
from .store.fulltext import KeywordLane
from .store.vectors import PgVectorStore


class HybridRetriever:
    def __init__(self, engine: AsyncEngine, embedder: Embedder | None = None) -> None:
        self.keyword = KeywordLane(engine)
        self.vectors = PgVectorStore(engine)
        self.embedder = embedder

    async def search(self, tenant: str, kb_ids: list[str], question: str, how: Search) -> Found:
        asked = list(how.lanes)
        ran: dict[str, list[dict[str, Any]]] = {}
        skipped: dict[str, str] = {}
        tokens = 0
        if not kb_ids or not question.strip():
            return Found([], list(asked), [], {})
        if "keyword" in how.lanes:
            ran["keyword"] = await self.keyword.hits(tenant, kb_ids, question, threshold=how.threshold, limit=how.limit)
        if "meaning" in how.lanes:
            why, hits, tokens = await self._meaning(tenant, kb_ids, question, how)
            if why:
                skipped["meaning"] = why
            else:
                ran["meaning"] = hits
        return Found(fuse(ran, how), list(asked), list(ran), skipped, tokens)

    async def _meaning(
        self, tenant: str, kb_ids: list[str], question: str, how: Search
    ) -> tuple[str | None, list[dict[str, Any]], int]:
        """(why it did not run, the hits above the threshold, the question's embedding tokens)."""
        embedder = self.embedder
        if embedder is None:
            return "no_embedding_model", [], 0
        if not await self.vectors.ready():
            return "no_vector_store", [], 0
        embedded, _ = await self.vectors.coverage(tenant, kb_ids, model=embedder.model, width=embedder.width)
        if embedded == 0:
            return "no_vectors", [], 0
        try:
            [vector], tokens = await embedder.embed([question], tenant=tenant)
        except EmbedFailed as e:
            return f"embedding_unavailable: {e.code}", [], 0
        rows = await self.vectors.nearest(
            tenant, kb_ids, vector, model=embedder.model, width=embedder.width, limit=how.limit
        )
        hits = [{**r, "lane_score": float(r["similarity"])} for r in rows if float(r["similarity"]) >= how.threshold]
        return None, hits, tokens


def lanes_for(mode: str) -> tuple[Lane, ...]:
    """A base's searchMode as lanes: keyword, meaning, or hybrid (both)."""
    if mode == "keyword":
        return ("keyword",)
    if mode == "meaning":
        return ("meaning",)
    return ("keyword", "meaning")
