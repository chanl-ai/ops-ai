# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""`faq`: write `questions_per_section` questions each chunk answers; each question is an index unit.

One model call per chunk, through the `ModelClient` the pipeline was given. A reply that is not the
requested JSON falls back to lines ending in `?`; a reply with no questions adds none and is noted.
"""

from __future__ import annotations

from knowledge_ingest.models import Chunk
from knowledge_ingest.strategies.base import SplitContext, json_list, json_object

MAX_TOKENS = 400

PROMPT = """Write {n} questions that a bank employee might ask and that the passage below answers.
Use the passage's own terms. Do not answer them.
Reply with JSON only: {{"questions": ["...", "..."]}}

Document: {title}
Section: {section}

Passage:
{text}
"""


def parse_questions(reply: str, limit: int) -> list[str]:
    data = json_object(reply)
    raw = json_list(data.get("questions")) if data is not None else None
    if raw is not None:
        questions = [str(q).strip() for q in raw if str(q).strip()]
    else:
        questions = [ln.strip(" -*0123456789.)\t") for ln in reply.splitlines() if ln.strip().endswith("?")]
    seen: set[str] = set()
    unique = [q for q in questions if not (q.lower() in seen or seen.add(q.lower()))]
    return unique[:limit]


def add_faq(chunks: list[Chunk], ctx: SplitContext) -> None:
    n = ctx.settings.questions_per_section
    for chunk in chunks:
        if chunk.kind == "row":
            continue
        prompt = PROMPT.format(n=n, title=ctx.title, section=" > ".join(chunk.section_path) or "-", text=chunk.text)
        questions = parse_questions(ctx.call_model(prompt, max_tokens=MAX_TOKENS), n)
        if not questions:
            ctx.notes.append(f"No questions were generated for chunk {chunk.index + 1}.")
        chunk.questions = questions
