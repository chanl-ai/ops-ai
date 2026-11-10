"""Lines repeated across a site: a footer the furniture rules missed, a disclaimer bar, a cookie line in plain text.
Each item keeps a short digest of each of its paragraphs; a line found on more than half of a source's pages (with at
least three pages) is dropped from every page before splitting. Counted after each sync of the source."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable

from ops_ingest import ParsedDocument
from ops_ingest.dedupe import normalise_text
from ops_ingest.models import Block, Paragraph, Section

# Lines shorter than this are headings or labels, and longer ones are content; neither is site furniture.
MIN_CHARS, MAX_CHARS = 20, 300
MIN_PAGES = 3


def line_digest(text: str) -> str | None:
    norm = normalise_text(text).lower()
    if not MIN_CHARS <= len(norm) <= MAX_CHARS:
        return None
    return hashlib.sha256(norm.encode()).hexdigest()[:12]


def lines_of(doc: ParsedDocument) -> list[str]:
    """The digests of the document's paragraphs a site could repeat, once each."""
    found = (line_digest(b.text) for s in doc.sections for b in s.blocks if isinstance(b, Paragraph))
    return sorted({d for d in found if d})


def repeated(pages: Iterable[list[str] | None]) -> list[str]:
    """The lines on more than half of the pages, when there are at least MIN_PAGES."""
    every = [set(p or []) for p in pages]
    if len(every) < MIN_PAGES:
        return []
    counts = Counter(d for page in every for d in page)
    return sorted(d for d, n in counts.items() if n * 2 > len(every))


def without(doc: ParsedDocument, lines: set[str]) -> ParsedDocument:
    """The document with its repeated lines dropped, counted as removed."""
    if not lines:
        return doc
    removed = 0
    sections: list[Section] = []
    for section in doc.sections:
        kept: list[Block] = []
        for block in section.blocks:
            if isinstance(block, Paragraph) and line_digest(block.text) in lines:
                removed += len(block.text)
                continue
            kept.append(block)
        sections.append(section.model_copy(update={"blocks": kept}))
    return doc.model_copy(update={"sections": sections, "removed_chars": doc.removed_chars + removed})
