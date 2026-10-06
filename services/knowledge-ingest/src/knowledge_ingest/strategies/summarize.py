# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Section summaries, stored on each chunk as `metadata["summary"]`.

Not selectable from ingest settings: the console's `IngestStrategy` has no `summarize`, so the
pipeline never runs it. It is kept for the later `ai:` metadata extraction and curation work (spec
14.15); wiring it into settings needs a contract change first.
"""

from __future__ import annotations

from knowledge_ingest.models import Chunk
from knowledge_ingest.strategies.base import SplitContext, json_object

MAX_TOKENS = 300

PROMPT = """Summarise the passage below in at most {words} words. Keep figures, dates, product names and
section numbers exactly as written. Do not add anything the passage does not say.
Reply with JSON only: {{"summary": "..."}}

Passage:
{text}
"""


def summarize_chunks(chunks: list[Chunk], ctx: SplitContext, *, words: int = 60) -> None:
    for chunk in chunks:
        if chunk.kind == "row":
            continue
        reply = ctx.call_model(PROMPT.format(words=words, text=chunk.text), max_tokens=MAX_TOKENS)
        data = json_object(reply)
        summary = str(data.get("summary", "")).strip() if data is not None else reply.strip()
        if summary:
            chunk.metadata["summary"] = summary
