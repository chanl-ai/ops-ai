"""Finding passages for a question: the `Retriever` port and its demo adapter, Postgres full-text search.

The demo adapter (store/fulltext.py) matches the question's terms with OR, so a natural question finds passages that
share some of its words, then scores each passage by the share of the question's terms it contains, with
`ts_rank_cd` breaking ties. A passage below the floor is never returned: a question nothing answers gets no passage
rather than a weak one. A pgvector adapter goes behind the same port once models-service serves an embeddings alias.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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
    score: float


class Retriever(Protocol):
    async def search(self, tenant: str, kb_ids: list[str], question: str, *, limit: int) -> list[Passage]: ...
