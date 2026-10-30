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
    # A file a document type is tested against (c-379): seeded with the type or added from Files.
    "document_type_sample",
    # An email's text, stored by the Email received trigger so a workflow reads it like an attachment (c-259).
    "email_body",
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


class FileData(Model):
    """What was read from the file, as the extract workflow records it (c-250): the document type and version it was
    read as, whether a template or the model read it, how many fields wait for a person, and the extraction. A file read
    with Detect whose kind is none of the team's types has no type and no version: it was not recognised (c-335)."""

    type_id: str | None = Field(default=None, min_length=1, max_length=64)
    # The type's display name when it was read, so the list shows it without asking documents-service per row.
    type_name: str | None = Field(default=None, max_length=200)
    version: int | None = Field(default=None, ge=1)
    path: Literal["template", "model"]
    template_id: str | None = Field(default=None, max_length=64)
    fields_to_check: int = Field(ge=0)
    extraction_id: str = Field(min_length=1, max_length=64)
    read_at: datetime


class ReadRequestIn(Model):
    """Read the file with a team's document type (c-250), the newest version when none is named; with no type, the file
    is classified over the team's types and read with the one found (Detect, c-335)."""

    document_type_id: str | None = Field(default=None, min_length=1, max_length=64)
    version: int | None = Field(default=None, ge=1)
    type_name: str | None = Field(default=None, max_length=200)
    # Fields the model proposes instead of a type's (c-535), with what the person said the file is; the first pages
    # only when `max_pages` is given. The full text is read on the file page from its layout, not through a request.
    read: Literal["fields", "propose"] | None = None
    hint: str | None = Field(default=None, max_length=200)
    max_pages: int | None = Field(default=None, ge=1)


class ReadRequest(Model):
    """A read request and the system extract run it started, once the event was delivered."""

    key: str
    file_id: str
    document_type_id: str | None
    version: int | None
    status: Literal["queued", "started", "unhandled"]
    run_id: str | None
    requested_by: str
    requested_at: datetime


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
    # What was read from it (c-250); None until the extract workflow records it.
    data: FileData | None = None


class FileDetail(FileRecord):
    versions: list[FileVersion] = Field(default_factory=list[FileVersion])
    references: list[FileReference] = Field(default_factory=list[FileReference])
    # Why the file cannot be deleted now (references, a hold, retention); None when it can. Set on the detail route.
    delete_blocked_by: str | None = None
    # What the caller may do with it (c-216), on the detail route only: a file is deleted, never edited or published.
    can_edit: bool | None = None
    can_delete: bool | None = None
    can_publish: bool | None = None


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
