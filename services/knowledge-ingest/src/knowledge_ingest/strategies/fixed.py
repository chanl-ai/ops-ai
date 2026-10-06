# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""`fixed`: equal windows of `size` tokens stepping by `size - overlap`, ignoring headings.

Windows are cut at word boundaries. Each chunk records the section and page its first word came from.
"""

from __future__ import annotations

from knowledge_ingest.models import Chunk, ParsedDocument
from knowledge_ingest.strategies.base import SplitContext, section_text


def split_fixed(document: ParsedDocument, ctx: SplitContext, *, include_tables: bool) -> list[Chunk]:
    words: list[tuple[str, int]] = []  # (word, section index)
    for i, section in enumerate(document.sections):
        words.extend((w, i) for w in section_text(section, include_tables=include_tables).split())
    if not words:
        return []

    size, overlap = ctx.settings.size, ctx.settings.overlap
    chunks: list[Chunk] = []
    start = 0
    while start < len(words):
        end = start
        while end < len(words) and (end == start or ctx.count(" ".join(w for w, _ in words[start : end + 1])) <= size):
            end += 1
        text = " ".join(w for w, _ in words[start:end])
        section = document.sections[words[start][1]]
        chunks.append(
            Chunk(index=0, text=text, indexed_text=text, section_path=list(section.heading_path), page=section.page)
        )
        if end >= len(words):
            break
        # Step back by `overlap` tokens, always moving forward by at least one word.
        back = end
        while back > start + 1 and ctx.count(" ".join(w for w, _ in words[back - 1 : end])) <= overlap:
            back -= 1
        start = back
    return chunks
