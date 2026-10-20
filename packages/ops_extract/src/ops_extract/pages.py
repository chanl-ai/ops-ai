"""A parsed document as one text per page, the text an extraction reads and quotes are checked against (c-235)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ops_ingest import ParsedDocument
from ops_ingest.models import Table


@dataclass(frozen=True)
class Pages:
    """Text by 1-based page (empty pages left out), the pages read by OCR, how many pages the document has, and on each
    OCR'd page each folded word's confidence when the reader kept it (a layout does; ops_ingest's text does not)."""

    texts: dict[int, str]
    ocr: set[int]
    count: int
    confidence: dict[int, dict[str, float]] = field(default_factory=dict[int, dict[str, float]])
    # The layout the text was rendered from, when there is one, so a field's quote can be found as boxes (c-252).
    layout: dict[str, Any] | None = None


def pages_of(doc: ParsedDocument) -> Pages:
    """Each section's heading, paragraphs and tables, in order, under the page they sit on. A page with no text layer
    that was not OCR'd has no text, so an unreadable scan is told apart from a short page."""
    texts: dict[int, list[str]] = {}
    for section in doc.sections:
        # ops_ingest opens a section at each heading it reads, and reads a title or a short line on its own such as
        # "Case reference: SYN-2026-0006" as one; left out, the model never sees it and a true quote from it scores 0.
        if section.heading_path and section.heading_path[-1].strip():
            texts.setdefault(section.page or 1, []).append(section.heading_path[-1])
        for block in section.blocks:
            page = block.page or section.page or 1
            text = block.as_text() if isinstance(block, Table) else block.text
            if text.strip():
                texts.setdefault(page, []).append(text)
    joined = {n: "\n".join(t) for n, t in texts.items()}
    count = max([*joined, *doc.pages_without_text, doc.source.page_count or 0, 1])
    return Pages(joined, {n for n in doc.ocr_pages if n in joined}, count)
