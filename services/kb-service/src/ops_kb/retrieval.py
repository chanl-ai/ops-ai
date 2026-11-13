"""Finding passages for a question: the `Retriever` port, and `HybridRetriever`, the one search every caller uses
(grounding, the search_knowledge tool, the Playground and the query route).

Two lanes run and are fused. The keyword lane (store/fulltext.py) scores a unit by the share of the question's terms
it holds; the meaning lane (store/vectors.py) by the cosine similarity of the question's vector to the unit's. Each
lane drops what falls below the bases' threshold, so a question nothing answers gets no passage rather than a weak
one. The rest are fused by reciprocal rank (k = 60), weighted toward meaning by the bases' hybrid weight; a piece found
by one lane only keeps that lane's part. A child, question or FAQ unit returns the piece it points at, each piece once
by its best unit, at most two from one item. Every result says which lanes were asked, which ran and why one did not
(no vectors yet, the embedding model down, no embedding model in this stack)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Lane = Literal["keyword", "meaning"]
LANES: tuple[Lane, ...] = ("keyword", "meaning")
# Reciprocal rank fusion's constant: rank 1 scores 1/61, so the top few of each lane stay close and neither lane's raw
# scale (a share of terms, a cosine) leaks into the order.
RRF_K = 60
# At most this many pieces from one document, so one long document never fills every passage.
PER_ITEM = 2


@dataclass(frozen=True)
class Passage:
    kb_id: str
    item_id: str
    version: int
    title: str
    section: str
    page: int | None
    text: str
    snippet: str
    # The fused score the order follows (reciprocal ranks, weighted); 0 to about 1/61.
    score: float
    # The unit that matched: the piece's own text (`self`), a smaller child, or a question written for it.
    matched: str = "self"
    matched_text: str = ""
    # The file this version was built from (an upload, or the snapshot of a fetched page), which a citation opens, and
    # the item's address where it came from.
    file_id: str | None = None
    url: str | None = None
    # Each lane's own score for this piece: keyword, the share of the question's terms; meaning, cosine similarity.
    lanes: dict[str, float] = field(default_factory=dict[str, float])
    chunk_id: str = ""
    # A person marked the item checked (its Verify action).
    verified: bool = False
    # The reranker's score from 0 to 10 when a rerank ran (query_steps.py).
    reranked: float | None = None


@dataclass(frozen=True)
class Scope:
    """Which of one base's pieces a search may return (its retrieval settings): empty lists allow everything. An
    excluded tag wins over an included one; `include_untagged` false drops documents whose source has no tag.
    `conditions` are (key, op, value) on each piece's metadata, all or any of them by `match`."""

    collections: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    tags_include: tuple[str, ...] = ()
    tags_exclude: tuple[str, ...] = ()
    include_untagged: bool = True
    match: str = "all"
    conditions: tuple[tuple[str, str, str], ...] = ()

    def narrows(self) -> bool:
        return bool(
            self.collections
            or self.source_ids
            or self.tags_include
            or self.tags_exclude
            or not self.include_untagged
            or self.conditions
        )


@dataclass(frozen=True)
class Search:
    """What the bases ask for: the lanes, the threshold each lane's score must reach, the weight toward meaning in
    the fusion, and how many pieces return."""

    lanes: tuple[Lane, ...] = LANES
    # The keyword lane's floor: the share of the question's terms a unit holds.
    threshold: float = 0.5
    # The meaning lane's floor: cosine similarity of the question's vector to the unit's. 0.38 kept 96% of answerable
    # questions' answering pieces and withheld 92% of unanswerable ones on OpenAI's text-embedding-3 models at 1,536
    # (docs/services/kb-service/experiments/meaning-threshold.md); a base on another model sets its own.
    meaning_threshold: float = 0.38
    weight: float = 0.6
    limit: int = 8
    # Each base's own scope by its id, applied in both lanes; a base not named is not narrowed.
    scopes: dict[str, Scope] = field(default_factory=dict[str, Scope])
    # One collection for every base, on top of their own scopes (the Test sheet's filter).
    collection: str | None = None


@dataclass(frozen=True)
class Found:
    passages: list[Passage]
    asked: list[str]
    ran: list[str]
    # Lane -> why it did not run: no_vectors, no_candidates, embedding_unavailable (with the model's code),
    # no_embedding_model, no_vector_store; the keyword lane's no_full_text (a database without full-text search).
    skipped: dict[str, str]
    # Input tokens the question's embedding cost, charged to kb-service's key at models-service.
    embedding_tokens: int = 0
    # The optional steps around the lanes (query_steps.py), as the answer shows them; None when not asked for.
    rewrite: dict[str, Any] | None = None
    rerank: dict[str, Any] | None = None

    def lanes_out(self) -> dict[str, Any]:
        return {
            "asked": self.asked,
            "ran": self.ran,
            "skipped": [{"lane": k, "reason": v} for k, v in self.skipped.items()],
        }


class Retriever(Protocol):
    async def search(self, tenant: str, kb_ids: list[str], question: str, how: Search) -> Found: ...


def snippet(text: str, width: int = 280) -> str:
    return text if len(text) <= width else text[: width - 1].rsplit(" ", 1)[0] + "…"


def fuse(lanes: dict[str, list[dict[str, Any]]], how: Search) -> list[Passage]:
    """Each lane's unit hits (best first, already above the threshold) to pieces, fused by weighted reciprocal rank."""
    weight = {"meaning": how.weight, "keyword": 1.0 - how.weight}
    if len(lanes) == 1:
        # One lane ran: its order is the order, at its full weight.
        weight = dict.fromkeys(lanes, 1.0)
    best: dict[str, dict[str, Any]] = {}
    scores: dict[str, float] = {}
    lane_scores: dict[str, dict[str, float]] = {}
    for lane, rows in lanes.items():
        rank = 0
        seen: set[str] = set()
        for r in rows:
            piece = str(r["chunk_id"])
            if piece in seen:
                continue
            seen.add(piece)
            rank += 1
            scores[piece] = scores.get(piece, 0.0) + weight[lane] / (RRF_K + rank)
            lane_scores.setdefault(piece, {})[lane] = round(float(r["lane_score"]), 3)
            # The unit named is the best one of the lane that ranked the piece highest.
            if piece not in best or rank < best[piece]["_rank"]:
                best[piece] = {**r, "_rank": rank}
    order = sorted(scores, key=lambda k: scores[k], reverse=True)
    per_item: dict[str, int] = {}
    out: list[Passage] = []
    for piece in order:
        r = best[piece]
        if per_item.get(r["item_id"], 0) >= PER_ITEM:
            continue
        per_item[r["item_id"]] = per_item.get(r["item_id"], 0) + 1
        out.append(
            Passage(
                kb_id=r["kb_id"],
                item_id=r["item_id"],
                version=r["version"],
                title=r["title"],
                section=r["section"],
                page=r["page"],
                text=r["text"],
                snippet=snippet(r["text"]),
                score=round(scores[piece], 5),
                matched=r["unit_kind"],
                matched_text=r["unit_text"],
                file_id=r["file_id"] or None,
                url=r["url"],
                lanes=lane_scores[piece],
                chunk_id=piece,
                verified=bool(r.get("verified")),
            )
        )
        if len(out) == how.limit:
            break
    return out
