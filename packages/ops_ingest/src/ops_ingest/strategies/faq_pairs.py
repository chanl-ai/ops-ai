# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""`faq_pairs`: draft question-and-answer pairs per section for a person to review, each tied to the exact passage it
came from.

One model call per section (the chunks that share a section path), up to MAX_PAIRS pairs. A pair's `quote` must be
copied from the section; a pair whose quote is not found in any of its chunks is dropped and noted, so every draft
cites text that is really there. A section whose text had pairs drafted before (`known_sections`, by section digest)
is not asked again. A model that does not answer, or the run's ceiling, stops the step and the notes say why.
"""

from __future__ import annotations

from ops_ingest.model_client import ModelBudgetSpent, ModelUnavailable
from ops_ingest.models import Chunk, FaqPair
from ops_ingest.strategies.base import SplitContext, json_list, json_object
from ops_ingest.strategies.faq import piece_digest

MAX_PAIRS = 8
MAX_TOKENS = 1_200

PROMPT = """Write up to {n} question-and-answer pairs that a customer or a colleague might ask and that the section
below answers. Answer in one or two sentences in the section's own terms. For each pair, copy into "quote" the exact
words of the section that hold the answer, unchanged. Use only what the section says.
Reply with JSON only: {{"pairs": [{{"question": "...", "answer": "...", "quote": "..."}}]}}

Document: {title}
Section: {section}

Section text:
{text}
"""


def section_digest(chunks: list[Chunk]) -> str:
    return piece_digest("\n".join(c.text for c in chunks))


def sections_of(chunks: list[Chunk]) -> list[list[Chunk]]:
    """The text chunks grouped by section path, in reading order."""
    groups: dict[tuple[str, ...], list[Chunk]] = {}
    for chunk in chunks:
        if chunk.kind != "row":
            groups.setdefault(tuple(chunk.section_path), []).append(chunk)
    return list(groups.values())


def locate(quote: str, chunks: list[Chunk]) -> tuple[Chunk, int, int] | None:
    """The chunk holding `quote` and its span there, matched with whitespace runs as one space and case ignored."""
    wanted = " ".join(quote.split()).lower()
    if not wanted:
        return None
    for chunk in chunks:
        # Positions in the flattened text map back to the chunk's own text by counting non-space characters.
        flat: list[str] = []
        where: list[int] = []
        prev_space = False
        for i, ch in enumerate(chunk.text):
            if ch.isspace():
                if prev_space or not flat:
                    continue
                prev_space = True
                flat.append(" ")
            else:
                prev_space = False
                flat.append(ch.lower())
            where.append(i)
        text = "".join(flat)
        at = text.find(wanted)
        if at >= 0:
            return chunk, where[at], where[at + len(wanted) - 1] + 1
    return None


def parse_pairs(reply: str) -> list[tuple[str, str, str]]:
    data = json_object(reply)
    raw = json_list(data.get("pairs")) if data is not None else None
    out: list[tuple[str, str, str]] = []
    for p in raw or []:
        if isinstance(p, dict):
            q, a, quote = (str(p.get(k) or "").strip() for k in ("question", "answer", "quote"))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            if q and a and quote:
                out.append((q, a, quote))
    return out


def draft_pairs(chunks: list[Chunk], ctx: SplitContext) -> list[FaqPair]:
    pairs: list[FaqPair] = []
    for section in sections_of(chunks):
        digest = section_digest(section)
        ctx.section_digests.append(digest)
        if digest in ctx.known_sections:
            continue
        path = tuple(section[0].section_path)
        text = "\n\n".join(c.text for c in section)
        prompt = PROMPT.format(n=MAX_PAIRS, title=ctx.title, section=" > ".join(path) or "-", text=text)
        try:
            reply = ctx.call_model(prompt, max_tokens=MAX_TOKENS)
        except ModelBudgetSpent as e:
            ctx.notes.append(f"FAQ drafts stopped at a spend ceiling: {e}")
            ctx.section_digests += [section_digest(rest) for rest in sections_of(chunks)[len(ctx.section_digests) :]]
            break
        except ModelUnavailable as e:
            ctx.notes.append(f"FAQ drafts stopped: the model did not answer ({e}).")
            ctx.section_digests += [section_digest(rest) for rest in sections_of(chunks)[len(ctx.section_digests) :]]
            break
        dropped = 0
        for question, answer, quote in parse_pairs(reply)[:MAX_PAIRS]:
            found = locate(quote, section)
            if found is None:
                dropped += 1
                continue
            chunk, start, end = found
            pairs.append(
                FaqPair(
                    chunk_index=chunk.index,
                    section_path=list(path),
                    section_digest=digest,
                    question=question,
                    answer=answer,
                    quote=chunk.text[start:end],
                    start=start,
                    end=end,
                )
            )
        if dropped:
            ctx.notes.append(f"{dropped} FAQ draft(s) for {' > '.join(path) or 'a section'} quoted text not in it.")
    return pairs
