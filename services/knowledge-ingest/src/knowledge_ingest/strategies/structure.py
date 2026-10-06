# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""`structure`: one chunk per section; a section over `size` splits at sentence ends with `overlap`.

Headings are not part of a chunk's text. They travel in `section_path`, and `context_headers` adds
them to what is indexed after splitting, so overlap never carries a heading into the next chunk.
"""

from __future__ import annotations

from knowledge_ingest.models import Chunk, ParsedDocument, Section
from knowledge_ingest.strategies.base import SplitContext, section_text
from knowledge_ingest.text import pack_sentences


def split_section(section: Section, ctx: SplitContext, *, include_tables: bool) -> list[Chunk]:
    text = section_text(section, include_tables=include_tables)
    if not text.strip():
        return []
    size, overlap = ctx.settings.size, ctx.settings.overlap
    pieces = [text] if ctx.count(text) <= size else pack_sentences(text, size, overlap, ctx.count)
    return [
        Chunk(index=0, text=p, indexed_text=p, section_path=list(section.heading_path), page=section.page)
        for p in pieces
    ]


def split_structure(document: ParsedDocument, ctx: SplitContext, *, include_tables: bool) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in document.sections:
        chunks.extend(split_section(section, ctx, include_tables=include_tables))
    return chunks
