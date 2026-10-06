# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Object-store adapters. Import a backend module directly so only its SDK is loaded."""

from ops_files.storage.base import (
    ExpiryTooLongError,
    InvalidKeyError,
    ObjectExistsError,
    ObjectInfo,
    ObjectLockedError,
    ObjectNotFoundError,
    ObjectStore,
    PresignedRequest,
    RetentionMode,
    RetentionShortenError,
    StorageError,
    UploadRejectedError,
)

__all__ = [
    "ExpiryTooLongError",
    "InvalidKeyError",
    "ObjectExistsError",
    "ObjectInfo",
    "ObjectLockedError",
    "ObjectNotFoundError",
    "ObjectStore",
    "PresignedRequest",
    "RetentionMode",
    "RetentionShortenError",
    "StorageError",
    "UploadRejectedError",
]
