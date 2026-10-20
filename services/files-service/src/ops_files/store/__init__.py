# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""files-service's door to its database; only this package imports the driver."""

from ops_files.store.files import AsyncEngine, FileRow, FilesStore, HoldRow, Page, engine_for, metadata, reachable
from ops_files.store.read_requests import ReadRequestsStore
from ops_files.store.settings import CredentialRow, SavedSettings, SettingsStore, StaleVersionError

__all__ = [
    "AsyncEngine",
    "CredentialRow",
    "FileRow",
    "FilesStore",
    "HoldRow",
    "Page",
    "ReadRequestsStore",
    "SavedSettings",
    "SettingsStore",
    "StaleVersionError",
    "engine_for",
    "metadata",
    "reachable",
]
