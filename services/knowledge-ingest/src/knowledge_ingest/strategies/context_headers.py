# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""`context_headers`: prefix what is indexed with the document title and section path.

Runs after splitting, so the header is added once per chunk and is never part of the text that
overlap carries into the next chunk. The returned `text` is unchanged.
"""

from __future__ import annotations

from knowledge_ingest.models import Chunk
from knowledge_ingest.strategies.base import SplitContext


def context_header(title: str, section_path: list[str]) -> str:
    # A document whose title is its first heading would otherwise read "Policy > Policy > Fees".
    path = section_path[1:] if section_path and section_path[0] == title else section_path
    return " > ".join([title, *path])


def add_context_headers(chunks: list[Chunk], ctx: SplitContext) -> None:
    for chunk in chunks:
        header = context_header(ctx.title, chunk.section_path)
        chunk.context_header = header
        chunk.indexed_text = f"{header}\n\n{chunk.indexed_text}"
