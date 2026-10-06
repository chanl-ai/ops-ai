# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""`topic`: group neighbouring sections that cover the same topic, up to `size` tokens.

One model call per document. The model sees each section's heading and opening and returns groups of
consecutive section numbers. A reply whose groups are not consecutive, skip a section or repeat one is
rejected and the document is split by structure instead, with a note: a model must not be able to drop
or reorder content.
"""

from __future__ import annotations

from typing import cast

from knowledge_ingest.models import Chunk, ParsedDocument, Section
from knowledge_ingest.strategies.base import SplitContext, json_list, json_object, section_text
from knowledge_ingest.strategies.structure import split_section, split_structure
from knowledge_ingest.text import pack_sentences

MAX_TOKENS = 600
PREVIEW_CHARS = 300

PROMPT = """Group these consecutive sections of one document by topic. Neighbouring sections about the
same topic go in one group. Every section number appears exactly once, in order.
Reply with JSON only: {{"groups": [[0, 1], [2], [3, 4]]}}

Document: {title}

{sections}
"""


def valid_groups(data: dict[str, object] | None, count: int) -> list[list[int]] | None:
    raw = json_list(data.get("groups")) if data is not None else None
    if raw is None:
        return None
    groups: list[list[int]] = []
    for item in raw:
        group = json_list(item)
        if not group or not all(isinstance(i, int) and not isinstance(i, bool) for i in group):
            return None
        groups.append([cast(int, i) for i in group])
    flat = [i for g in groups for i in g]
    return groups if flat == list(range(count)) else None


def split_topic(document: ParsedDocument, ctx: SplitContext, *, include_tables: bool) -> list[Chunk]:
    sections = [s for s in document.sections if section_text(s, include_tables=include_tables).strip()]
    if len(sections) < 2:
        return split_structure(document, ctx, include_tables=include_tables)

    listing = "\n\n".join(
        f"[{i}] {' > '.join(s.heading_path) or '(no heading)'}\n"
        f"{section_text(s, include_tables=include_tables)[:PREVIEW_CHARS]}"
        for i, s in enumerate(sections)
    )
    reply = ctx.call_model(PROMPT.format(title=ctx.title, sections=listing), max_tokens=MAX_TOKENS)
    groups = valid_groups(json_object(reply), len(sections))
    if groups is None:
        ctx.notes.append("The topic grouping reply was not usable, so the document was split by structure.")
        return split_structure(document, ctx, include_tables=include_tables)

    chunks: list[Chunk] = []
    for group in groups:
        members: list[Section] = [sections[i] for i in group]
        if len(members) == 1:
            chunks.extend(split_section(members[0], ctx, include_tables=include_tables))
            continue
        text = "\n".join(section_text(s, include_tables=include_tables) for s in members)
        size, overlap = ctx.settings.size, ctx.settings.overlap
        pieces = [text] if ctx.count(text) <= size else pack_sentences(text, size, overlap, ctx.count)
        first = members[0]
        chunks.extend(
            Chunk(index=0, text=p, indexed_text=p, section_path=list(first.heading_path), page=first.page)
            for p in pieces
        )
    return chunks
