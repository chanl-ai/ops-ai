# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""documents-service's refusals, each mapped to one HTTP answer by the app."""

from __future__ import annotations


class DocumentsError(Exception):
    """A refusal the caller can act on."""


class FileMissingError(DocumentsError):
    """files-service has no such file for the caller's team (404 there, 404 here)."""


class FileNotReadyError(DocumentsError):
    """The file is not scanned clean, or is quarantined, so it is not read (409)."""


class DocumentTypeMissingError(DocumentsError):
    """No document type (or version) of that id in the caller's team (404)."""


class InvalidRequestError(DocumentsError):
    """The request names something wrong: a field type, a record, a value (400)."""


class StateError(DocumentsError):
    """The extraction is not in a state this asks for, such as correcting one not done (409)."""


class IdempotencyConflictError(DocumentsError):
    """The Idempotency-Key was used for a different request (409)."""


class CreateNotAllowedError(DocumentsError):
    """The caller reads the team's documents but may not change them: documents.edit in the team (403)."""
