# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Files service library: every file byte in the platform goes through `FileService`."""

from ops_files.models import CompletedUpload, DownloadLink, FileDetail, FileRecord, UploadRequest, UploadTicket
from ops_files.repository import FileRepository, InMemoryFileRepository
from ops_files.scanning import EicarScanner, Scanner, ScanResult
from ops_files.service import FilesConfig, FileService

__all__ = [
    "CompletedUpload",
    "DownloadLink",
    "EicarScanner",
    "FileDetail",
    "FileRecord",
    "FileRepository",
    "FileService",
    "FilesConfig",
    "InMemoryFileRepository",
    "ScanResult",
    "Scanner",
    "UploadRequest",
    "UploadTicket",
]
