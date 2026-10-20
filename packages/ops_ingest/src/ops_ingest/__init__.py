# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Knowledge ingestion library: parse, split, map metadata, dedupe and apply source rules."""

from ops_ingest.model_client import ModelClient
from ops_ingest.models import IngestSettings, ParsedDocument, ParsingSettings, SplitResult
from ops_ingest.parsers import parse
from ops_ingest.split import InvalidIngestError, Pipeline, split, validate_settings

__all__ = [
    "IngestSettings",
    "InvalidIngestError",
    "ModelClient",
    "ParsedDocument",
    "ParsingSettings",
    "Pipeline",
    "SplitResult",
    "parse",
    "split",
    "validate_settings",
]
