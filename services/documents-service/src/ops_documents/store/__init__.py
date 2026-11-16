# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""documents-service's door to its database; only this package imports the driver."""

from ops_documents.store.document_types import DocumentTypesStore, NameTakenError
from ops_documents.store.extractions import ExtractionRow, ExtractionsStore
from ops_documents.store.metadata import engine_for, metadata
from ops_documents.store.readings import ReadingsStore
from ops_documents.store.relay import ROUTES, documents_relay
from ops_documents.store.template_copies import TemplateCopies

__all__ = [
    "ROUTES",
    "DocumentTypesStore",
    "ExtractionRow",
    "ExtractionsStore",
    "NameTakenError",
    "ReadingsStore",
    "TemplateCopies",
    "documents_relay",
    "engine_for",
    "metadata",
]
