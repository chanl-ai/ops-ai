"""A keyword passage store standing in for the knowledge service, so chat replies carry real citations."""

from __future__ import annotations

import re

from ops_agent_kernel.types import Passage

from .catalog import Catalog

_WORD = re.compile(r"[a-z0-9$]+")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "at",
        "be",
        "by",
        "can",
        "do",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "our",
        "the",
        "to",
        "we",
        "what",
        "when",
        "which",
        "who",
        "with",
        "you",
        "your",
    ]
)
# Below this many shared terms a passage is not returned; the turn then answers "not found" rather than guessing.
MIN_SHARED_TERMS = 2


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


class KeywordPassageStore:
    def __init__(self, catalog: Catalog) -> None:
        self._passages = [
            (
                Passage(p.document_id, p.title, p.section, p.version, p.text, p.kb_id),
                _terms(f"{p.title} {p.section} {p.text}"),
            )
            for p in catalog.passages
        ]

    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Passage]:
        q = _terms(query)
        scored = [(len(q & terms), p) for p, terms in self._passages if p.kb_id in kb_ids]
        ranked = sorted((s for s in scored if s[0] >= MIN_SHARED_TERMS), key=lambda s: -s[0])
        return [p for _, p in ranked[:k]]
