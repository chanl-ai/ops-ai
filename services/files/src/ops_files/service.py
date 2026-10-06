# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The Files service: the only code that reads or writes file bytes. Other services hold `file_id`s.

`team` and `actor` arguments come from platform context (the caller's token), never from request bodies,
file names or model output. A file in another team is reported as missing, so a caller cannot learn that a
file id exists outside its team.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import PurePosixPath

from ops_files.models import (
    CompletedUpload,
    DownloadLink,
    FileDetail,
    FileReference,
    FileReferenceType,
    FileRetention,
    FileScan,
    FileVersion,
    LegalHold,
    PurposeLimit,
    RetentionClass,
    StorageEnvironment,
    StorageLocation,
    StoredFile,
    UploadRequest,
    UploadTicket,
)
from ops_files.repository import FileRepository
from ops_files.scanning import Scanner, ScanResult
from ops_files.storage.base import ObjectStore

_TEAM = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class FilesError(Exception):
    """Base class for refusals by the Files service."""


class FileMissingError(FilesError):
    """No such file in the caller's team."""


class InvalidUploadError(FilesError):
    pass


class UploadStateError(FilesError):
    pass


class UploadMissingError(FilesError):
    """`complete_upload` found no object at the upload key."""


class UploadVerificationError(FilesError):
    """The stored object does not match the declared upload; it has been deleted."""


class SizeMismatchError(UploadVerificationError):
    pass


class TypeMismatchError(UploadVerificationError):
    pass


class DigestMismatchError(UploadVerificationError):
    pass


class NotDownloadableError(FilesError):
    pass


class QuarantinedError(NotDownloadableError):
    pass


class NotScannedError(NotDownloadableError):
    pass


class DownloadTtlError(FilesError):
    pass


class DeleteRefusedError(FilesError):
    pass


class FileReferencedError(DeleteRefusedError):
    pass


class FileHeldError(DeleteRefusedError):
    pass


class FileRetainedError(DeleteRefusedError):
    pass


class RetentionChangeError(FilesError):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return f"fil_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class FilesConfig:
    retention_classes: tuple[RetentionClass, ...]
    default_retention_class: str
    environment: StorageEnvironment = "dev"
    region: str = ""
    # KMS key alias (S3) or encryption scope (Azure Blob), shown on the admin storage location.
    encryption: str = ""
    upload_url_seconds: int = 900
    max_download_url_seconds: int = 300
    max_upload_bytes: int = 100 * 1024 * 1024
    limits: tuple[PurposeLimit, ...] = field(default_factory=tuple[PurposeLimit, ...])

    def retention_class(self, class_id: str) -> RetentionClass:
        for item in self.retention_classes:
            if item.id == class_id:
                return item
        raise InvalidUploadError(f"unknown retention class {class_id!r}")


def display_name(name: str) -> str:
    """The name shown to people. It is metadata only and never part of a storage key."""
    base = PurePosixPath(name.replace("\\", "/")).name
    cleaned = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C").strip()
    if cleaned in {"", ".", ".."}:
        raise InvalidUploadError("file name is empty")
    return cleaned[:255]


def _retain_until(day: date) -> datetime:
    # A file kept "until" a date stays locked for the whole of that date in UTC.
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=UTC)


class FileService:
    def __init__(
        self,
        store: ObjectStore,
        repository: FileRepository,
        config: FilesConfig,
        *,
        scanner: Scanner | None = None,
        clock: Callable[[], datetime] = _utcnow,
        new_id: Callable[[], str] = _new_id,
    ) -> None:
        if config.max_download_url_seconds > store.max_url_seconds:
            raise ValueError("max_download_url_seconds exceeds what the store signs")
        for item in config.retention_classes:
            if item.worm and item.days is None:
                raise ValueError(f"retention class {item.id} is WORM and needs a period")
        config.retention_class(config.default_retention_class)
        self._store = store
        self._repo = repository
        self._config = config
        self._scanner = scanner
        self._clock = clock
        self._new_id = new_id

    # ── helpers ──

    def _owned(self, file_id: str, team: str) -> StoredFile:
        record = self._repo.get(file_id)
        if record is None or record.team != team:
            raise FileMissingError(file_id)
        return record

    def _key(self, record: StoredFile) -> str:
        assert record.storage is not None
        return record.storage.key

    @staticmethod
    def _detail(record: StoredFile) -> FileDetail:
        return FileDetail.model_validate(record.model_dump(include=set(FileDetail.model_fields)))

    def _check_limits(self, request: UploadRequest, name: str) -> None:
        limit = next((item for item in self._config.limits if item.purpose == request.purpose), None)
        max_bytes = limit.max_size_mb * 1024 * 1024 if limit else self._config.max_upload_bytes
        if request.size > max_bytes:
            raise InvalidUploadError(f"{request.size} bytes exceeds the {max_bytes}-byte limit for {request.purpose}")
        if limit and limit.allowed_types:
            extension = PurePosixPath(name).suffix.lstrip(".").lower()
            if extension not in limit.allowed_types:
                raise InvalidUploadError(f".{extension} is not allowed for {request.purpose}")

    # ── upload ──

    def create_upload(self, request: UploadRequest, *, team: str, actor: str) -> UploadTicket:
        if not _TEAM.fullmatch(team):
            raise InvalidUploadError(f"invalid team {team!r}")
        if request.team is not None and request.team != team:
            raise InvalidUploadError("the owning team comes from the caller's context")
        name = display_name(request.name)
        self._check_limits(request, name)
        retention = self._config.retention_class(request.retention_class or self._default_class(request))
        now = self._clock()
        file_id = self._new_id()
        key = f"{team}/{request.purpose}/{now:%Y}/{now:%m}/{file_id}"
        ticket = self._store.presign_put(
            key, content_type=request.mime, max_bytes=request.size, expires_in=self._config.upload_url_seconds
        )
        record = StoredFile(
            id=file_id,
            name=name,
            mime=request.mime,
            size=request.size,
            purpose=request.purpose,
            team=team,
            uploaded_by=actor,
            uploaded_at=now,
            sensitivity=request.sensitivity,
            retention=FileRetention(
                class_id=retention.id,
                class_name=retention.name,
                delete_after=now.date() + timedelta(days=retention.days) if retention.days is not None else None,
            ),
            storage=self._location(key),
            declared_size=request.size,
            declared_digest=request.digest,
            upload_expires_at=ticket.expires_at,
        )
        self._repo.save(record)
        return UploadTicket(
            file_id=file_id,
            upload_url=ticket.url,
            method=ticket.method,
            headers=dict(ticket.headers),
            expires_at=ticket.expires_at,
        )

    def _default_class(self, request: UploadRequest) -> str:
        for item in self._config.retention_classes:
            if request.purpose in item.purposes:
                return item.id
        return self._config.default_retention_class

    def _location(self, key: str, *, locked: bool = False) -> StorageLocation:
        return StorageLocation(
            backend=self._store.backend,
            environment=self._config.environment,
            container=self._store.container,
            key=key,
            region=self._config.region,
            encryption=self._config.encryption,
            locked=locked,
        )

    def _reject(self, record: StoredFile, error: UploadVerificationError) -> UploadVerificationError:
        self._store.delete(self._key(record))
        record.status = "rejected"
        self._repo.save(record)
        return error

    def complete_upload(self, file_id: str, *, team: str) -> CompletedUpload:
        record = self._owned(file_id, team)
        if record.status == "available":
            return CompletedUpload(file=self._detail(record), deduplicated=False)
        if record.status != "uploading":
            raise UploadStateError(f"{file_id} is {record.status}")
        key = self._key(record)
        info = self._store.head(key)
        if info is None:
            raise UploadMissingError(file_id)
        if info.size != record.declared_size:
            raise self._reject(record, SizeMismatchError(f"stored {info.size} bytes; declared {record.declared_size}"))
        if info.content_type != record.mime:
            raise self._reject(record, TypeMismatchError(f"stored {info.content_type}; declared {record.mime}"))

        # The digest is computed from the stored bytes. A client-supplied digest is only compared against it,
        # so dedupe can never hand one caller another object on the strength of a claim.
        digest, size = self._digest(self._store.iter_bytes(key))
        if size != record.declared_size:
            raise self._reject(record, SizeMismatchError(f"read {size} bytes; declared {record.declared_size}"))
        if record.declared_digest is not None and record.declared_digest != digest:
            raise self._reject(
                record, DigestMismatchError(f"stored sha256 {digest}; declared {record.declared_digest}")
            )

        existing = self._repo.find_available_by_digest(team, digest)
        if existing is not None:
            self._store.delete(key)
            self._repo.remove(record.id)
            return CompletedUpload(file=self._detail(existing), deduplicated=True)

        now = self._clock()
        record.digest = digest
        record.status = "available"
        record.upload_expires_at = None
        record.versions = [
            FileVersion(
                version=1, digest=digest, size=size, uploaded_by=record.uploaded_by, uploaded_at=now, current=True
            )
        ]
        record.version_count = 1
        if self._scanner is not None:
            self._apply_scan(record, self._scanner.scan(self._store.iter_bytes(key)))
        retention = self._config.retention_class(record.retention.class_id)
        if retention.worm and record.retention.delete_after is not None:
            self._store.set_retention(key, _retain_until(record.retention.delete_after), "compliance")
            record.immutable = True
            record.storage = self._location(key, locked=True)
        self._repo.save(record)
        return CompletedUpload(file=self._detail(record), deduplicated=False)

    @staticmethod
    def _digest(chunks: Iterable[bytes]) -> tuple[str, int]:
        hasher = hashlib.sha256()
        size = 0
        for chunk in chunks:
            hasher.update(chunk)
            size += len(chunk)
        return hasher.hexdigest(), size

    # ── read ──

    def get(self, file_id: str, *, team: str) -> FileDetail:
        return self._detail(self._owned(file_id, team))

    def download_url(self, file_id: str, *, team: str, expires_in: int | None = None) -> DownloadLink:
        record = self._owned(file_id, team)
        if record.status != "available":
            raise UploadStateError(f"{file_id} is {record.status}")
        if record.scan.status == "infected":
            raise QuarantinedError(f"{file_id} is quarantined: {record.scan.detail}")
        if record.scan.status != "clean":
            raise NotScannedError(f"{file_id} scan is {record.scan.status}")
        ttl = expires_in if expires_in is not None else self._config.max_download_url_seconds
        if not 0 < ttl <= self._config.max_download_url_seconds:
            raise DownloadTtlError(f"download links last at most {self._config.max_download_url_seconds} seconds")
        url = self._store.presign_get(self._key(record), expires_in=ttl, filename=record.name)
        return DownloadLink(url=url, expires_at=self._clock() + timedelta(seconds=ttl), ttl_seconds=ttl)

    # ── references ──

    def add_reference(
        self,
        file_id: str,
        *,
        team: str,
        type: FileReferenceType,
        ref_id: str,
        name: str,
        href: str | None = None,
    ) -> FileDetail:
        record = self._owned(file_id, team)
        if record.status != "available":
            raise UploadStateError(f"{file_id} is {record.status}")
        if not any(ref.type == type and ref.id == ref_id for ref in record.references):
            blocked = f"Quarantined: {record.scan.detail}" if record.scan.status == "infected" else None
            record.references.append(
                FileReference(type=type, id=ref_id, name=name, href=href, added_at=self._clock(), blocked=blocked)
            )
            record.reference_count = len(record.references)
            self._repo.save(record)
        return self._detail(record)

    def remove_reference(
        self,
        file_id: str,
        *,
        team: str,
        type: FileReferenceType,
        ref_id: str,
    ) -> FileDetail:
        record = self._owned(file_id, team)
        record.references = [ref for ref in record.references if not (ref.type == type and ref.id == ref_id)]
        record.reference_count = len(record.references)
        self._repo.save(record)
        return self._detail(record)

    # ── delete ──

    def delete(self, file_id: str, *, team: str) -> None:
        record = self._owned(file_id, team)
        if record.references:
            raise FileReferencedError(f"{file_id} is used by {len(record.references)} record(s)")
        if record.legal_hold is not None:
            raise FileHeldError(f"{file_id} is under legal hold")
        retention = self._config.retention_class(record.retention.class_id)
        delete_after = record.retention.delete_after
        if (
            (retention.keep_until_end or retention.worm or record.immutable)
            and delete_after is not None
            and self._clock().date() <= delete_after
        ):
            raise FileRetainedError(f"{file_id} is retained until {delete_after.isoformat()}")
        key = self._key(record)
        if self._store.head(key) is not None:
            self._store.delete(key)
        self._repo.remove(file_id)

    # ── scanning ──

    def _apply_scan(self, record: StoredFile, result: ScanResult) -> None:
        record.scan = FileScan(status=result.status, engine=result.engine, at=self._clock(), detail=result.detail)
        blocked = f"Quarantined: {result.detail}" if result.status == "infected" else None
        record.references = [ref.model_copy(update={"blocked": blocked}) for ref in record.references]

    def record_scan(self, file_id: str, result: ScanResult) -> FileDetail:
        """Scan-result hook for an asynchronous scanner. Internal: not exposed to teams."""
        record = self._repo.get(file_id)
        if record is None:
            raise FileMissingError(file_id)
        self._apply_scan(record, result)
        self._repo.save(record)
        return self._detail(record)

    def quarantine(self, file_id: str, *, engine: str, detail: str) -> FileDetail:
        return self.record_scan(file_id, ScanResult("infected", engine, detail))

    # ── retention and holds ──

    def set_retention(self, file_id: str, *, team: str, class_id: str) -> FileDetail:
        record = self._owned(file_id, team)
        new = self._config.retention_class(class_id)
        new_until = record.uploaded_at.date() + timedelta(days=new.days) if new.days is not None else None
        current_until = record.retention.delete_after
        if record.immutable:
            if not new.worm:
                raise RetentionChangeError(f"{file_id} is immutable; its retention cannot be removed")
            if current_until is not None and (new_until is None or new_until < current_until):
                raise RetentionChangeError(f"{file_id} is immutable until {current_until.isoformat()}")
        if new.worm and new_until is not None:
            self._store.set_retention(self._key(record), _retain_until(new_until), "compliance")
            record.immutable = True
            record.storage = self._location(self._key(record), locked=True)
        record.retention = FileRetention(class_id=new.id, class_name=new.name, delete_after=new_until)
        self._repo.save(record)
        return self._detail(record)

    def set_legal_hold(self, file_id: str, *, team: str, on: bool, by: str, reason: str = "") -> FileDetail:
        record = self._owned(file_id, team)
        self._store.set_legal_hold(self._key(record), on)
        record.legal_hold = LegalHold(by=by, at=self._clock(), reason=reason) if on else None
        self._repo.save(record)
        return self._detail(record)
