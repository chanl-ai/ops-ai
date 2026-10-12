# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Files domain types. They mirror `apps/console/src/lib/types/files.ts` in snake_case and accept the
console's camelCase JSON unchanged."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

FilePurpose = Literal[
    "knowledge_source",
    "chat_attachment",
    "case_attachment",
    "test_import",
    "evidence_bundle",
    "export",
    "tool_spec",
    "avatar",
]
ScanStatus = Literal["pending", "clean", "infected", "failed"]
FileSensitivity = Literal["public", "internal", "confidential", "restricted"]
# `local` is the development backend; the console's `StorageBackend` has only the two cloud values.
StorageBackendName = Literal["s3", "azure_blob", "local"]
StorageEnvironment = Literal["dev", "test", "prod"]
FileReferenceType = Literal["source", "case", "chat", "eval_set", "test_set", "evidence", "export", "tool_module"]
FileStatus = Literal["uploading", "available", "rejected"]


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class StorageLocation(Model):
    backend: StorageBackendName
    environment: StorageEnvironment
    container: str
    key: str
    region: str = ""
    encryption: str = ""
    locked: bool = False


class FileReference(Model):
    type: FileReferenceType
    id: str
    name: str
    href: str | None = None
    added_at: datetime
    blocked: str | None = None


class FileVersion(Model):
    version: int
    digest: str
    size: int
    uploaded_by: str
    uploaded_at: datetime
    current: bool


class FileScan(Model):
    status: ScanStatus = "pending"
    engine: str | None = None
    at: datetime | None = None
    detail: str | None = None


class FileRetention(Model):
    class_id: str
    class_name: str
    delete_after: date | None = None


class LegalHold(Model):
    by: str
    at: datetime
    reason: str


class FileRecord(Model):
    id: str
    name: str
    mime: str
    size: int
    digest: str = ""
    purpose: FilePurpose
    team: str
    uploaded_by: str
    uploaded_at: datetime
    scan: FileScan = Field(default_factory=FileScan)
    sensitivity: FileSensitivity = "internal"
    sensitivity_suggested: bool = True
    retention: FileRetention
    legal_hold: LegalHold | None = None
    immutable: bool = False
    reference_count: int = 0
    version_count: int = 0
    storage: StorageLocation | None = None


class FileDetail(FileRecord):
    versions: list[FileVersion] = Field(default_factory=list[FileVersion])
    references: list[FileReference] = Field(default_factory=list[FileReference])


class StoredFile(FileDetail):
    """What the repository keeps: the detail plus upload state the API does not return."""

    status: FileStatus = "uploading"
    declared_size: int
    declared_digest: str | None = None
    upload_expires_at: datetime | None = None


class UploadRequest(Model):
    name: str
    size: int = Field(gt=0)
    mime: str
    purpose: FilePurpose
    team: str | None = None
    retention_class: str | None = None
    digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    sensitivity: FileSensitivity = "internal"


class UploadTicket(Model):
    file_id: str
    upload_url: str
    method: Literal["PUT"]
    headers: dict[str, str]
    expires_at: datetime


class CompletedUpload(Model):
    file: FileDetail
    deduplicated: bool


class DownloadLink(Model):
    url: str
    expires_at: datetime
    ttl_seconds: int


class RetentionClass(Model):
    id: str
    name: str
    days: int | None
    purposes: list[FilePurpose] = Field(default_factory=list[FilePurpose])
    worm: bool = False
    keep_until_end: bool = False


class PurposeLimit(Model):
    purpose: FilePurpose
    allowed_types: list[str]
    max_size_mb: int
