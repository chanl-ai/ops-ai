# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Ingestion strategies (spec 5.14). Compose them through `knowledge_ingest.split.Pipeline`."""

from knowledge_ingest.strategies.base import SplitContext
from knowledge_ingest.strategies.clean import clean_document
from knowledge_ingest.strategies.context_headers import add_context_headers, context_header
from knowledge_ingest.strategies.faq import add_faq
from knowledge_ingest.strategies.fixed import split_fixed
from knowledge_ingest.strategies.parent_child import add_parent_child
from knowledge_ingest.strategies.structure import split_structure
from knowledge_ingest.strategies.summarize import summarize_chunks
from knowledge_ingest.strategies.table_rows import parse_band, split_table
from knowledge_ingest.strategies.topic import split_topic

__all__ = [
    "SplitContext",
    "add_context_headers",
    "add_faq",
    "add_parent_child",
    "clean_document",
    "context_header",
    "parse_band",
    "split_fixed",
    "split_structure",
    "split_table",
    "split_topic",
    "summarize_chunks",
]
