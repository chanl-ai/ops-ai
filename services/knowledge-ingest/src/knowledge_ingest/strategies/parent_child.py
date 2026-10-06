# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""`parent_child`: index children of `child_size` tokens; a match on a child returns the whole parent.

The parent keeps its full `text`, which is what a query returns. Children exist only as index units
(`SplitResult.index_units`), each pointing back at the parent's index.
"""

from __future__ import annotations

from knowledge_ingest.models import Chunk
from knowledge_ingest.strategies.base import SplitContext
from knowledge_ingest.text import pack_sentences


def add_parent_child(chunks: list[Chunk], ctx: SplitContext) -> None:
    for chunk in chunks:
        if chunk.kind == "row":
            continue
        chunk.kind = "parent"
        chunk.children = pack_sentences(chunk.text, ctx.settings.child_size, 0, ctx.count)
