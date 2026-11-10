"""The embedding model as a test drives it. Meaning is a bag of concepts: each word the small dictionary below knows
counts toward its concept, so "clear my loan sooner" and "early repayment of a loan" are close although they share
one word, and a test can say which piece the meaning lane must find. A trace of each text's own words (scripted
vectors) keeps unrelated texts apart and no vector empty. A switch makes it refuse as models-service does when the
model is down."""

from __future__ import annotations

import math
import re

from ops_kb.embedding import EmbedFailed
from ops_service_kit.scripted_vectors import scripted_vector

CONCEPTS: dict[str, tuple[str, ...]] = {
    "repay": ("repay", "repayment", "repaying", "clear", "settle", "paying"),
    "early": ("early", "sooner", "ahead"),
    "charge": ("charge", "charges", "fee", "fees", "cost", "costs"),
    "loan": ("loan", "loans", "borrowing", "mortgage"),
    "claim": ("claim", "claims"),
    "late": ("late", "belatedly", "delay", "after"),
    "notify": ("tell", "telling", "notify", "notifying", "notification", "report", "reporting"),
}
_BY_WORD = {w: i for i, words in enumerate(CONCEPTS.values()) for w in words}
_WORD = re.compile(r"[a-z]+")


def concept_vector(text: str, width: int) -> list[float]:
    trace = scripted_vector(text, width)
    v = [0.15 * x for x in trace]
    for word in _WORD.findall(text.lower()):
        if (i := _BY_WORD.get(word)) is not None:
            v[i] += 1.0
    norm = math.hypot(*v) or 1.0
    return [x / norm for x in v]


class ConceptEmbedder:
    def __init__(self, model: str = "concept-embed", width: int = 64) -> None:
        self.model, self.width = model, width
        self.down: str | None = None
        self.texts = 0

    async def embed(self, texts: list[str], *, tenant: str) -> tuple[list[list[float]], int]:
        if self.down:
            raise EmbedFailed(self.down, "the embedding model did not answer")
        self.texts += len(texts)
        return [concept_vector(t, self.width) for t in texts], sum(len(t.split()) for t in texts)
