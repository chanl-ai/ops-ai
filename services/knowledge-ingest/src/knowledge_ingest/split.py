# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The split: one function from a parsed document and ingest settings to chunks and index units.

Spec 5.18: the sync workflow and `sources.previewSplit` both call this, so the preview shows what a
re-index produces. It is pure apart from model calls, which go through the `ModelClient` it is given.

Order of steps:

1. `clean` on the parsed text.
2. Tables to `row` chunks under `table_rows`; otherwise tables stay in their section's text.
3. One splitter over the remaining text: `structure` (default), `fixed` or `topic`.
4. `parent_child` children for non-row chunks.
5. `faq` questions for non-row chunks.
6. `context_headers` last, so headers are added once to finished chunks and never split or overlapped.
"""

from __future__ import annotations

from typing import Literal

from knowledge_ingest.dedupe import content_digest
from knowledge_ingest.model_client import ModelClient
from knowledge_ingest.models import (
    AI_STEPS,
    SPLITTERS,
    Chunk,
    IngestSettings,
    IngestStrategy,
    ParsedDocument,
    SplitCounts,
    SplitResult,
)
from knowledge_ingest.strategies.base import SplitContext
from knowledge_ingest.strategies.clean import clean_document
from knowledge_ingest.strategies.context_headers import add_context_headers
from knowledge_ingest.strategies.faq import add_faq
from knowledge_ingest.strategies.fixed import split_fixed
from knowledge_ingest.strategies.parent_child import add_parent_child
from knowledge_ingest.strategies.structure import split_structure
from knowledge_ingest.strategies.table_rows import split_table
from knowledge_ingest.strategies.topic import split_topic
from knowledge_ingest.text import TokenCounter, approx_tokens

MIN_SIZE, MAX_SIZE = 100, 2_000

PRESETS: dict[str, list[IngestStrategy]] = {
    "policy_manual": ["structure", "context_headers", "parent_child"],
    "help_centre": ["clean", "structure", "faq"],
    "rate_table": ["table_rows"],
    "email_templates": ["structure", "context_headers"],
}

_STEP_NAMES = {"topic": "Topic grouping", "faq": "FAQ questions"}


class InvalidIngestError(ValueError):
    """Settings the API refuses with `invalid_ingest` (spec 14.1 to 14.4). `message` is what the form shows."""

    code: Literal["invalid_ingest"] = "invalid_ingest"


def validate_settings(settings: IngestSettings) -> None:
    strategies = settings.strategies
    splitters = [s for s in strategies if s in SPLITTERS]
    if len(splitters) > 1:
        raise InvalidIngestError(f"Choose one way to split: {', '.join(splitters)} cannot be combined.")
    if "parent_child" in strategies and "fixed" in strategies:
        raise InvalidIngestError(
            "Parent and child chunks need sections, so they cannot be used with fixed-size splitting."
        )
    if not MIN_SIZE <= settings.size <= MAX_SIZE:
        raise InvalidIngestError(f"Chunk size must be between {MIN_SIZE} and {MAX_SIZE} tokens.")
    if not 0 <= settings.overlap < settings.size:
        raise InvalidIngestError("Overlap must be zero or more and smaller than the chunk size.")
    if "parent_child" in strategies and not 0 < settings.child_size < settings.size:
        raise InvalidIngestError("Child chunks must be smaller than the chunk size.")
    if "table_rows" in strategies and settings.columns:
        if not any(c.role == "searchable" for c in settings.columns):
            raise InvalidIngestError("At least one table column must be searchable.")
        keys = [c for c in settings.columns if c.key]
        if len(keys) > 1:
            raise InvalidIngestError("Only one column can be the key.")
        if keys and keys[0].role != "searchable":
            raise InvalidIngestError("The key column must be searchable.")
    if any(s in AI_STEPS for s in strategies) and not settings.model:
        raise InvalidIngestError("AI steps need a model alias.")


def preset_for(strategies: list[IngestStrategy]) -> str:
    """The preset id the API stores: a named preset when the strategies match one, else `custom`."""
    wanted = set(strategies)
    return next((pid for pid, steps in PRESETS.items() if set(steps) == wanted), "custom")


def ai_step_allowed(settings: IngestSettings, step: IngestStrategy, *, preview: bool) -> bool:
    """Spec 14.9 and 14.12: the preview runs AI steps on its sample; syncs need the owner's approval."""
    if preview:
        return True
    approval = settings.approval
    return approval.status == "approved" and step in approval.approved_steps


class Pipeline:
    def __init__(
        self,
        settings: IngestSettings,
        *,
        model: ModelClient | None = None,
        count_tokens: TokenCounter = approx_tokens,
    ) -> None:
        validate_settings(settings)
        self.settings = settings
        self.model = model
        self.count_tokens = count_tokens

    def run(self, document: ParsedDocument, *, preview: bool = False) -> SplitResult:
        settings = self.settings
        ctx = SplitContext(settings=settings, title=document.title, count=self.count_tokens, model=self.model)
        strategies = settings.strategies

        def ai(step: IngestStrategy) -> bool:
            if step not in strategies:
                return False
            if not ai_step_allowed(settings, step, preview=preview):
                ctx.notes.append(f"{_STEP_NAMES[step]} skipped: waiting for the knowledge owner's approval.")
                return False
            if self.model is None:
                raise RuntimeError(f"{step} is approved but the pipeline has no model client")
            return True

        if "clean" in strategies:
            document, removed = clean_document(document)
            ctx.removed_chars += removed

        chunks: list[Chunk] = []
        rows = "table_rows" in strategies
        if rows:
            if document.tables:
                for section in document.sections:
                    for table in section.tables:
                        chunks.extend(split_table(table, section, ctx))
            else:
                ctx.notes.append("This document has no tables, so it was split as text.")

        include_tables = not rows
        if "fixed" in strategies:
            chunks.extend(split_fixed(document, ctx, include_tables=include_tables))
        elif "topic" in strategies and ai("topic"):
            chunks.extend(split_topic(document, ctx, include_tables=include_tables))
        else:
            if not any(s in SPLITTERS for s in strategies) and not (rows and document.tables):
                ctx.notes.append("No splitter was chosen, so the document was split at its headings.")
            chunks.extend(split_structure(document, ctx, include_tables=include_tables))

        # Row chunks first, then text, in document order within each; numbered once all are known.
        for i, chunk in enumerate(chunks):
            chunk.index = i
            chunk.tokens = ctx.count(chunk.text)

        if "parent_child" in strategies:
            add_parent_child(chunks, ctx)
        if ai("faq"):
            add_faq(chunks, ctx)
        if "context_headers" in strategies:
            add_context_headers(chunks, ctx)

        result = SplitResult(
            title=document.title,
            strategies=list(strategies),
            chunks=chunks,
            counts=SplitCounts(),
            notes=ctx.notes,
        )
        result.counts = SplitCounts(
            chunks=len(chunks),
            indexed_units=len(result.index_units()),
            questions=sum(len(c.questions or []) for c in chunks),
            tokens=sum(c.tokens for c in chunks),
            model_calls=ctx.model_calls,
            removed_chars=document.removed_chars + ctx.removed_chars,
        )
        return result


def split(
    document: ParsedDocument,
    settings: IngestSettings,
    *,
    model: ModelClient | None = None,
    preview: bool = False,
    count_tokens: TokenCounter = approx_tokens,
) -> SplitResult:
    return Pipeline(settings, model=model, count_tokens=count_tokens).run(document, preview=preview)


def document_digest(document: ParsedDocument, settings: IngestSettings) -> str:
    """Spec 1.6: `contentDigest` is SHA-256 of the extracted text after `clean`."""
    if "clean" in settings.strategies:
        document, _ = clean_document(document)
    return content_digest(document.plain_text())
