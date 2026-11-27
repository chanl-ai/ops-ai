"""HybridRetriever: the keyword and meaning lanes behind the Retriever port (retrieval.py), on the service's own
PostgreSQL. The meaning lane runs when this stack has an embedding model and the bases' units have vectors of it; when
it cannot, the result says why and the keyword lane answers alone."""

from __future__ import annotations

import asyncio

from .embedding import Embedder, EmbedFailed
from .retrieval import Found, Lane, Search, fuse
from .store import AsyncEngine
from .store.fulltext import KeywordHit, KeywordLane
from .store.vectors import MeaningHit, PgVectorStore


class HybridRetriever:
    def __init__(self, engine: AsyncEngine, embedder: Embedder | None = None) -> None:
        self.keyword = KeywordLane(engine)
        self.vectors = PgVectorStore(engine)
        self.embedder = embedder

    async def search(
        self, tenant: str, kb_ids: list[str], question: str, how: Search, *, deadline: float | None = None
    ) -> Found:
        asked = list(how.lanes)
        ran: dict[str, list[KeywordHit] | list[MeaningHit]] = {}
        skipped: dict[str, str] = {}
        tokens = 0
        if not kb_ids or not question.strip():
            return Found([], list(asked), [], {})
        if "keyword" in how.lanes:
            if self.keyword.ready():
                ran["keyword"] = await self.keyword.hits(
                    tenant, kb_ids, question, threshold=how.threshold, limit=how.limit, how=how
                )
            else:
                skipped["keyword"] = "no_full_text"
        if "meaning" in how.lanes:
            why, hits, tokens = await self._meaning(tenant, kb_ids, question, how, deadline)
            if why:
                skipped["meaning"] = why
            else:
                ran["meaning"] = hits
        return Found(fuse(ran, how), list(asked), list(ran), skipped, tokens)

    async def _meaning(
        self, tenant: str, kb_ids: list[str], question: str, how: Search, deadline: float | None
    ) -> tuple[str | None, list[MeaningHit], int]:
        """(why it did not run, the hits above the threshold, the question's embedding tokens)."""
        embedder = self.embedder
        if embedder is None:
            return "no_embedding_model", [], 0
        if not await self.vectors.ready():
            return "no_vector_store", [], 0
        # No call before the question's own: a process that has not heard from the model yet compares with the model
        # of the newest stored vectors, so the reason a search gives does not depend on how long the process has run.
        before = embedder.model or await self.vectors.latest_model(tenant, width=embedder.width)
        embedded, _ = await self.vectors.coverage(tenant, kb_ids, model=before, width=embedder.width)
        if embedded == 0:
            return "no_vectors", [], 0
        try:
            async with asyncio.timeout_at(deadline):
                [vector], tokens = await embedder.embed([question], tenant=tenant)
        except EmbedFailed as e:
            return f"embedding_unavailable: {e.code}", [], 0
        except TimeoutError:
            return "embedding_unavailable: timeout", [], 0
        if embedder.model != before:
            # The alias now serves another model: vectors of the old one are never compared with the question.
            embedded, _ = await self.vectors.coverage(tenant, kb_ids, model=embedder.model, width=embedder.width)
            if embedded == 0:
                return "no_vectors", [], tokens
        rows = await self.vectors.nearest(
            tenant, kb_ids, vector, model=embedder.model, width=embedder.width, limit=how.limit, how=how
        )
        if not rows:
            # The index answered no candidate in these bases at all: the lane did not run in any useful sense.
            return "no_candidates", [], tokens
        floor = how.meaning_threshold
        hits = [MeaningHit(**r, lane_score=float(r["similarity"])) for r in rows if float(r["similarity"]) >= floor]
        return None, hits, tokens


def lanes_for(mode: str) -> tuple[Lane, ...]:
    """A base's searchMode as lanes: keyword, meaning, or hybrid (both)."""
    if mode == "keyword":
        return ("keyword",)
    if mode == "meaning":
        return ("meaning",)
    return ("keyword", "meaning")
