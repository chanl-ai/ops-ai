# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""documents-service's door to its database; only this package imports the driver."""

from ops_documents.store.document_types import DocumentTypesStore, NameTakenError
from ops_documents.store.extractions import ExtractionRow, ExtractionsStore
from ops_documents.store.layouts import LayoutsStore
from ops_documents.store.metadata import engine_for, metadata

__all__ = [
    "DocumentTypesStore",
    "ExtractionRow",
    "ExtractionsStore",
    "LayoutsStore",
    "NameTakenError",
    "engine_for",
    "metadata",
]
