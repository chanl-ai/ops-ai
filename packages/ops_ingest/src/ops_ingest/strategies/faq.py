# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""`faq`: write `questions_per_section` questions each chunk answers; each question is an index unit.

One model call per chunk, through the `ModelClient` the pipeline was given. A reply that is not the
requested JSON falls back to lines ending in `?`; a reply with no questions adds none and is noted. A chunk whose text
had questions written before (`known_questions`, by `piece_digest`) keeps them with no call. A model that does not
answer, or the run's ceiling, stops the step: the rest of the chunks get no questions, and the notes say why.
"""

from __future__ import annotations

import hashlib

from ops_ingest.model_client import ModelBudgetSpent, ModelUnavailable
from ops_ingest.models import Chunk
from ops_ingest.strategies.base import SplitContext, json_list, json_object

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


def piece_digest(text: str) -> str:
    """What decides whether a piece changed: its text, with whitespace runs made one space."""
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()[:32]


def add_faq(chunks: list[Chunk], ctx: SplitContext) -> None:
    n = ctx.settings.questions_per_section
    stopped = False
    for chunk in chunks:
        if chunk.kind == "row":
            continue
        known = ctx.known_questions.get(piece_digest(chunk.text))
        if known is not None:
            chunk.questions = known[:n]
            continue
        if stopped:
            continue
        prompt = PROMPT.format(n=n, title=ctx.title, section=" > ".join(chunk.section_path) or "-", text=chunk.text)
        try:
            reply = ctx.call_model(prompt, max_tokens=MAX_TOKENS)
        except ModelBudgetSpent:
            ctx.notes.append("Likely questions stopped at this sync's ceiling on model calls.")
            stopped = True
            continue
        except ModelUnavailable as e:
            ctx.notes.append(f"Likely questions stopped: the model did not answer ({e}).")
            stopped = True
            continue
        questions = parse_questions(reply, n)
        if not questions:
            ctx.notes.append(f"No questions were generated for chunk {chunk.index + 1}.")
        chunk.questions = questions
