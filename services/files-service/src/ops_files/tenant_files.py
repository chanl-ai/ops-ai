# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The hosted files-service's use cases: every file is held to the caller's tenant and team, and its bytes move on the
storage adapter's async byte path (obstore).

The tenant always comes from the caller's token and the team from the token or, for a service, from the platform
record it acts for; never from a request body. A file in another tenant or team is reported missing, so a caller
cannot learn that the id exists. `FileService` stays the sync library for in-process callers until they move here.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import re
import uuid
from collections.abc import AsyncIterable, AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from ops_files.models import (
    CompletedUpload,
    DownloadLink,
    FileData,
    FileDetail,
    FilePurpose,
    FileReference,
    FileReferenceType,
    FileRetention,
    FileScan,
    FileVersion,
    LegalHold,
    ReadRequest,
    ReadRequestIn,
    StorageLocation,
    UploadRequest,
    UploadTicket,
)
from ops_files.scanning import Scanner, ScanResult
from ops_files.service import (
    DeleteNotAllowedError,
    DeleteRefusedError,
    DigestMismatchError,
    DownloadTtlError,
    EditNotAllowedError,
    FileHeldError,
    FileMissingError,
    FileReferencedError,
    FileRetainedError,
    FilesConfig,
    FilesError,
    InvalidUploadError,
    NotDownloadableError,
    NotScannedError,
    QuarantinedError,
    SizeMismatchError,
    TypeNotAllowedError,
    UploadMissingError,
    UploadStateError,
    UploadVerificationError,
    check_limits,
    check_type,
    default_class,
    display_name,
    retain_until,
)
from ops_files.sniffing import SNIFF_BYTES, prove
from ops_files.store import AsyncEngine, FileRow, FilesStore, HoldRow, ReadRequestsStore
from ops_service_kit.http import options_page, options_window
from ops_storage.base import ObjectExistsError, StreamingObjectStore

if TYPE_CHECKING:
    from ops_files.settings import StorageSettings

_TEAM = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_REF_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

# off: development only, files are clean at completion (files 5.3.1). inline: the configured scanner reads the bytes
# at completion. hook: files stay pending until a scanner posts its result to the scan-results route.
ScanningMode = Literal["off", "inline", "hook"]

# The purpose of a file a document type is tested against (c-379); it gives way to any other on dedupe (c-380).
SAMPLE_PURPOSE = "document_type_sample"

# Suggested from purpose until a person confirms it (files 5.5.1).
_SENSITIVITY: dict[str, str] = {
    "evidence_bundle": "restricted",
    "export": "restricted",
    "case_attachment": "confidential",
    "document_type_sample": "confidential",
    "email_body": "confidential",
    "chat_attachment": "confidential",
    "knowledge_source": "internal",
    "avatar": "public",
}


class HoldRefusedError(Exception):
    """Placing or releasing a hold needs an admin of the file's team; `app` answers 403."""


class IdempotencyConflictError(UploadStateError):
    """An Idempotency-Key reused with a different request, or for a file that has been deleted; answered 409."""


class ReasonRequiredError(InvalidUploadError):
    """A hold placed or released without a reason (files 5.6.4)."""


@dataclass(frozen=True)
class Who:
    """The caller, from its token: tenant, the team it acts in, who it is, and the teams it administers."""

    tenant_id: str
    team: str
    actor: str
    admin_teams: frozenset[str] = field(default_factory=frozenset[str])
    # files.delete in the team, as `can()` decides it (c-216): every member role holds it, a chat-only member does not.
    deletes: bool = True
    # Whether the caller may record what was read from a file (c-250): files:edit for a service, files.create for a
    # person until the extract workflow's step writes it.
    edits: bool = True


def _read_request(row: Mapping[str, Any]) -> ReadRequest:
    return ReadRequest(
        key=row["request_key"],
        file_id=row["file_id"],
        document_type_id=row["document_type_id"],
        version=row["version"],
        status=row["status"],
        run_id=row["run_id"],
        requested_by=row["requested_by"],
        requested_at=row["requested_at"],
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return f"fil_{uuid.uuid4().hex}"


async def _counted(chunks: AsyncIterable[bytes], limit: int, seen: list[int]) -> AsyncIterator[bytes]:
    """Passes `chunks` through, counting bytes, and stops the stream once it is longer than `limit`."""
    async for chunk in chunks:
        seen[0] += len(chunk)
        if seen[0] > limit:
            raise SizeMismatchError(f"the body is longer than the declared {limit} bytes")
        yield chunk


class TenantFiles:
    def __init__(
        self,
        store: StreamingObjectStore,
        files: FilesStore,
        config: FilesConfig,
        *,
        scanning: ScanningMode = "off",
        scanner: Scanner | None = None,
        proxy: bool | None = None,
        clock: Callable[[], datetime] = _utcnow,
        new_id: Callable[[], str] = _new_id,
        settings: StorageSettings | None = None,
    ) -> None:
        """`proxy`: browsers send and fetch bytes through this service instead of signed storage URLs. Always on for
        the local backend, which has no HTTP endpoint of its own; on elsewhere when a bank's network blocks browsers
        from storage. `settings`: the tenant's saved storage settings (c-100), which choose each purpose's target,
        limits and retention; without them every file goes to `store` under `config`."""
        if scanning == "inline" and scanner is None:
            raise ValueError("scanning 'inline' needs a scanner")
        if scanning == "off" and config.environment == "prod":
            raise ValueError("scanning 'off' is for development only")
        if config.max_download_url_seconds > store.max_url_seconds:
            raise ValueError("max_download_url_seconds exceeds what the store signs")
        config.retention_class(config.default_retention_class)
        self._store = store
        self._files = files
        self._config = config
        self._scanning: ScanningMode = scanning
        self._scanner = scanner
        self.proxy = store.backend == "local" if proxy is None else proxy or store.backend == "local"
        self._clock = clock
        self._new_id = new_id
        self._settings = settings

    @property
    def engine(self) -> AsyncEngine:
        return self._files.engine

    @property
    def settings(self) -> StorageSettings | None:
        return self._settings

    # ── helpers ──

    async def _config_for(self, tenant: str) -> FilesConfig:
        return await self._settings.config_for(tenant) if self._settings else self._config

    async def _upload_placement(self, tenant: str, purpose: str) -> tuple[StreamingObjectStore, bool]:
        if self._settings is None:
            return self._store, self.proxy
        placed = await self._settings.for_upload(tenant, purpose)
        return placed.store, placed.proxy

    async def _placement(self, row: FileRow | Mapping[str, Any]) -> tuple[StreamingObjectStore, bool]:
        """The store a file was written to, from its recorded backend and container: a change of target never moves
        files, so reads, deletes and holds go where the bytes are."""
        if self._settings is None or (row["storage_backend"], row["storage_container"]) == (
            self._store.backend,
            self._store.container,
        ):
            return self._store, self.proxy
        placed = await self._settings.located(row["tenant_id"], row["storage_backend"], row["storage_container"])
        return placed.store, placed.proxy

    async def _owned(self, who: Who, file_id: str) -> FileRow:
        row = await self._files.get(who.tenant_id, file_id)
        if row is None or row["team"] != who.team:
            raise FileMissingError(file_id)
        return row

    async def request_read(self, who: Who, file_id: str, body: ReadRequestIn, *, key: str | None) -> ReadRequest:
        """Asks for a clean file of the caller's team to be read with a document type (c-250): the request and its
        file.read_requested event commit together, and the system extract workflow runs as the caller once the relay
        delivers it. A repeat with the same key returns the first request."""
        if not who.edits:
            raise EditNotAllowedError("your role in this team does not change files")
        row = await self._owned(who, file_id)
        self._readable(row)
        values = {
            "tenant_id": who.tenant_id,
            "request_key": f"{file_id}:{key or uuid.uuid4().hex}",
            "file_id": file_id,
            "team": row["team"],
            "requested_by": who.actor,
            "document_type_id": body.document_type_id,
            "version": body.version,
            "type_name": body.type_name,
            "requested_at": self._clock(),
        }
        payload = {
            "fileId": file_id,
            "fileName": row["name"],
            "documentTypeId": body.document_type_id,
            "version": body.version,
            "typeName": body.type_name,
        }
        return _read_request(await ReadRequestsStore(self._files.engine).request(values, payload))

    async def read_request(self, who: Who, file_id: str, key: str) -> ReadRequest:
        await self._owned(who, file_id)
        found = await ReadRequestsStore(self._files.engine).get(who.tenant_id, key)
        if found is None or found["file_id"] != file_id:
            raise FileMissingError(key)
        return _read_request(found)

    async def set_data(self, who: Who, file_id: str, data: FileData) -> FileDetail:
        """Records what was read from an available file of the caller's team, replacing what was recorded before."""
        if not who.edits:
            raise EditNotAllowedError("your role in this team does not change files")
        row = await self._owned(who, file_id)
        if row["status"] != "available":
            raise UploadStateError(f"{file_id} is {row['status']}")
        stored = data.model_dump(mode="json", by_alias=True)
        await self._files.update(
            who.tenant_id, file_id, {"data": stored, "read_as": data.type_id, "read_path": data.path}
        )
        found = await self._files.get(who.tenant_id, file_id)
        assert found is not None
        return self._detail(found, who)

    def _detail(self, row: FileRow, who: Who | None) -> FileDetail:
        """The file as `who` may see it. The storage location (container and key) goes to admins of the file's team
        only (files 8.1); services and other members get none."""
        f = row.file
        sees_storage = who is not None and f["team"] in who.admin_teams
        retention = self._config.retention_class(f["retention_class_id"])
        references = [
            FileReference(
                type=r["ref_type"],
                id=r["ref_id"],
                name=r["name"],
                href=r["href"],
                added_at=r["added_at"],
                blocked=r["blocked"],
            )
            for r in row.references
        ]
        return FileDetail(
            id=f["id"],
            name=f["name"],
            mime=f["mime"],
            size=f["size"],
            digest=f["digest"] or "",
            purpose=f["purpose"],
            team=f["team"],
            uploaded_by=f["uploaded_by"],
            uploaded_at=f["uploaded_at"],
            scan=FileScan(status=f["scan_status"], engine=f["scan_engine"], at=f["scan_at"], detail=f["scan_detail"]),
            sensitivity=f["sensitivity"],
            sensitivity_suggested=f["sensitivity_suggested"],
            retention=FileRetention(class_id=retention.id, class_name=retention.name, delete_after=f["delete_after"]),
            legal_hold=LegalHold(by=row.hold.placed_by, at=row.hold.placed_at, reason=row.hold.reason)
            if row.hold
            else None,
            immutable=f["immutable"],
            reference_count=len(references),
            version_count=f["version_count"],
            data=FileData.model_validate(f["data"]) if f.get("data") else None,
            storage=StorageLocation(
                backend=f["storage_backend"],
                environment=self._config.environment,
                container=f["storage_container"],
                key=f["storage_key"],
                region=self._config.region,
                encryption=self._config.encryption,
                locked=f["immutable"],
            )
            if sees_storage
            else None,
            versions=[
                FileVersion(
                    version=v["version"],
                    digest=v["digest"],
                    size=v["size"],
                    uploaded_by=v["uploaded_by"],
                    uploaded_at=v["uploaded_at"],
                    current=v["current"],
                )
                for v in row.versions
            ],
            references=references,
        )

    def _row_detail(self, f: Mapping[str, Any], who: Who) -> dict[str, Any]:
        """A list row: the record without versions and references, in the console's JSON."""
        hold = HoldRow("", f["hold_by"], f["hold_at"], f["hold_reason"]) if f.get("hold_by") else None
        detail = self._detail(FileRow(file=f, versions=[], references=[], hold=hold), who)
        out = detail.model_dump(
            mode="json",
            by_alias=True,
            exclude={"versions", "references", "delete_blocked_by", "can_edit", "can_delete", "can_publish"},
        )
        out["referenceCount"] = int(f.get("reference_count", 0))
        return out

    # ── upload ──

    async def _ticket(
        self, store: StreamingObjectStore, proxy: bool, *, file_id: str, key: str, mime: str, size: int
    ) -> UploadTicket:
        if proxy:
            expires_at = self._clock() + timedelta(seconds=self._config.upload_url_seconds)
            url, headers = f"/v1/files/uploads/{file_id}/content", {"Content-Type": mime}
        else:
            signed = await asyncio.to_thread(
                store.presign_put,
                key,
                content_type=mime,
                max_bytes=size,
                expires_in=self._config.upload_url_seconds,
            )
            url, headers, expires_at = signed.url, dict(signed.headers), signed.expires_at
        return UploadTicket(file_id=file_id, upload_url=url, method="PUT", headers=headers, expires_at=expires_at)

    async def _replay(self, who: Who, claimed: tuple[str, str], request_hash: str) -> UploadTicket:
        """The ticket an Idempotency-Key already holds: the same file, a fresh URL. The key with another request is
        refused, so a retry can never swap what was asked for."""
        file_id, held_hash = claimed
        if held_hash != request_hash:
            raise IdempotencyConflictError("this Idempotency-Key was used for a different upload")
        row = await self._files.get(who.tenant_id, file_id)
        if row is None or row["team"] != who.team:
            raise IdempotencyConflictError("the file this Idempotency-Key created has been deleted")
        store, proxy = await self._placement(row)
        return await self._ticket(
            store, proxy, file_id=file_id, key=row["storage_key"], mime=row["mime"], size=row["declared_size"]
        )

    async def create_upload(
        self, who: Who, request: UploadRequest, *, idempotency_key: str | None = None
    ) -> UploadTicket:
        """A ticket for one upload. With `idempotency_key`, a retry by the same caller in the same team gets the same
        file id back instead of a second upload (files F1)."""
        if not _TEAM.fullmatch(who.team):
            raise InvalidUploadError(f"invalid team {who.team!r}")
        if request.team is not None and request.team != who.team:
            raise InvalidUploadError("the owning team comes from the caller's context")
        name = display_name(request.name)
        config = await self._config_for(who.tenant_id)
        check_limits(config, request)
        chosen = await self._settings.retention_for(who.tenant_id, request.purpose) if self._settings else None
        retention = config.retention_class(request.retention_class or chosen or default_class(config, request))
        claim: dict[str, str] | None = None
        request_hash = ""
        if idempotency_key is not None:
            if not 0 < len(idempotency_key) <= 255:
                raise InvalidUploadError("Idempotency-Key is 1 to 255 characters")
            # Outside text is indexed only through its hash (database portability D7).
            scope = "\n".join([who.tenant_id, who.team, who.actor, idempotency_key])
            request_hash = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
            claim = {"key_hash": hashlib.sha256(scope.encode()).hexdigest(), "request_hash": request_hash}
            held = await self._files.idempotent_upload(who.tenant_id, claim["key_hash"])
            if held is not None:
                return await self._replay(who, held, request_hash)
        now = self._clock()
        file_id = self._new_id()
        key = f"{who.tenant_id}/{who.team}/{request.purpose}/{now:%Y}/{now:%m}/{file_id}"
        store, proxy = await self._upload_placement(who.tenant_id, request.purpose)
        ticket = await self._ticket(store, proxy, file_id=file_id, key=key, mime=request.mime, size=request.size)
        values: dict[str, Any] = {
            "id": file_id,
            "tenant_id": who.tenant_id,
            "team": who.team,
            "name": name,
            "mime": request.mime,
            "size": request.size,
            "purpose": request.purpose,
            "status": "uploading",
            "scan_status": "pending",
            "sensitivity": request.sensitivity
            if "sensitivity" in request.model_fields_set
            else _SENSITIVITY.get(request.purpose, "internal"),
            "sensitivity_suggested": "sensitivity" not in request.model_fields_set,
            "retention_class_id": retention.id,
            "delete_after": now.date() + timedelta(days=retention.days) if retention.days is not None else None,
            "immutable": False,
            "storage_backend": store.backend,
            "storage_container": store.container,
            "storage_key": key,
            "declared_size": request.size,
            "declared_digest": request.digest,
            "upload_expires_at": ticket.expires_at,
            "uploaded_by": who.actor,
            "uploaded_at": now,
            "version_count": 0,
        }
        winner = await self._files.insert_upload(values, idempotency=claim)
        if winner is not None:
            # A concurrent request with the same key inserted first; nothing of this one was written.
            return await self._replay(who, winner, request_hash)
        return ticket

    async def put_content(self, who: Who, file_id: str, chunks: AsyncIterable[bytes], *, content_type: str) -> None:
        """The proxy upload: the bytes of an open upload, streamed into storage with the ticket's checks."""
        row = await self._owned(who, file_id)
        store, proxy = await self._placement(row)
        if not proxy:
            raise UploadStateError("uploads go to the signed storage URL; this service does not take the bytes")
        if row["status"] != "uploading":
            raise UploadStateError(f"{file_id} is {row['status']}")
        if row["upload_expires_at"] is not None and self._clock() >= row["upload_expires_at"]:
            raise UploadStateError(f"the upload ticket for {file_id} has expired")
        if content_type != row["mime"]:
            raise UploadVerificationError(f"sent {content_type}; the ticket is for {row['mime']}")
        seen = [0]
        try:
            await store.put_stream(
                row["storage_key"], _counted(chunks, row["declared_size"], seen), content_type=row["mime"]
            )
        except ObjectExistsError as error:
            raise UploadStateError(f"{file_id} already has its bytes") from error

    async def complete(self, who: Who, file_id: str) -> CompletedUpload:
        row = await self._owned(who, file_id)
        if row["status"] == "available":
            return CompletedUpload(file=self._detail(row, who), deduplicated=False)
        if row["status"] != "uploading":
            raise UploadStateError(f"{file_id} is {row['status']}")
        key = row["storage_key"]
        store, _ = await self._placement(row)
        info = await asyncio.to_thread(store.head, key)
        if info is None:
            raise UploadMissingError(file_id)
        declared = row["declared_size"]
        if info.size != declared:
            raise await self._reject(row, SizeMismatchError(f"stored {info.size} bytes; declared {declared}"))
        try:
            head = await store.read_range(key, start=0, length=min(SNIFF_BYTES, declared))
            proven = prove(row["mime"], row["name"], head)
            check_type(await self._config_for(who.tenant_id), row["purpose"], proven.mime, proven.extensions)
        except (UploadVerificationError, TypeNotAllowedError) as error:
            raise await self._reject(row, error) from None

        # The digest is computed from the stored bytes; a declared digest is only compared with it, so dedupe never
        # hands a caller another team's object, or another object, on the strength of a claim.
        hasher, size = hashlib.sha256(), 0
        async for chunk in store.open_read(key):
            hasher.update(chunk)
            size += len(chunk)
        digest = hasher.hexdigest()
        if size != declared:
            raise await self._reject(row, SizeMismatchError(f"read {size} bytes; declared {declared}"))
        if row["declared_digest"] is not None and row["declared_digest"] != digest:
            raise await self._reject(
                row, DigestMismatchError(f"stored sha256 {digest}; declared {row['declared_digest']}")
            )

        now = self._clock()
        values: dict[str, Any] = {
            "digest": digest,
            "mime": proven.mime,
            "sniffed_mime": proven.mime if proven.signed else None,
            "status": "available",
            "upload_expires_at": None,
            "version_count": 1,
        }
        if self._scanning == "off":
            values.update(scan_status="clean", scan_engine="off", scan_at=now, scan_detail="scanning is off")
        elif self._scanning == "inline":
            assert self._scanner is not None
            result = await asyncio.to_thread(self._scanner.scan, store.iter_bytes(key))
            values.update(scan_status=result.status, scan_engine=result.engine, scan_at=now, scan_detail=result.detail)
        version = {
            "version": 1,
            "digest": digest,
            "size": size,
            "storage_key": key,
            "uploaded_by": row["uploaded_by"],
            "uploaded_at": now,
            "current": True,
        }
        existing = await self._files.make_available(who.tenant_id, file_id, values, version)
        if existing == file_id:
            # Another complete of this same ticket won the race and made it available; this one is a repeat, and
            # deleting the object or the row here would delete the file it just completed.
            done = await self._files.get(who.tenant_id, file_id)
            assert done is not None
            return CompletedUpload(file=self._detail(done, who), deduplicated=False)
        if existing is not None:
            await asyncio.to_thread(store.delete, key)
            await self._files.repoint_idempotency(who.tenant_id, file_id, existing)
            await self._files.remove(who.tenant_id, file_id)
            first = await self._files.get(who.tenant_id, existing)
            assert first is not None
            if first.file["purpose"] == SAMPLE_PURPOSE and row["purpose"] != SAMPLE_PURPOSE:
                # Files shows what people use a file for (c-380): a document type sample's bytes arriving as a mail or
                # chat attachment take that purpose. Nothing else changes on dedupe, so an attachment later uploaded
                # as a sample stays the attachment.
                await self._files.update(who.tenant_id, existing, {"purpose": row["purpose"]})
                first = await self._files.get(who.tenant_id, existing)
                assert first is not None
            return CompletedUpload(file=self._detail(first, who), deduplicated=True)

        retention = self._config.retention_class(row["retention_class_id"])
        if retention.worm and row["delete_after"] is not None:
            await asyncio.to_thread(store.set_retention, key, retain_until(row["delete_after"]), "compliance")
            await self._files.update(who.tenant_id, file_id, {"immutable": True})
        done = await self._files.get(who.tenant_id, file_id)
        assert done is not None
        return CompletedUpload(file=self._detail(done, who), deduplicated=False)

    async def _reject[E: FilesError](self, row: FileRow, error: E) -> E:
        store, _ = await self._placement(row)
        await asyncio.to_thread(store.delete, row["storage_key"])
        await self._files.update(row["tenant_id"], row["id"], {"status": "rejected"})
        return error

    # ── read ──

    async def get(self, who: Who, file_id: str) -> FileDetail:
        row = await self._owned(who, file_id)
        return self._detail(row, who).model_copy(update={"delete_blocked_by": self.delete_blocked_by(row)})

    async def limits(self, who: Who) -> dict[str, Any]:
        """What the upload component enforces before asking for a ticket: the tenant's purpose limits, the ones
        `create_upload` checks, and whether files are scanned."""
        config = await self._config_for(who.tenant_id)
        return {
            "perPurpose": [item.model_dump(mode="json", by_alias=True) for item in config.limits],
            "scanning": self._scanning != "off",
        }

    async def options(
        self, who: Who, *, search: str, cursor: str | None, limit: int, ids: list[str] | None
    ) -> dict[str, Any]:
        """The file picker: the team's files labelled by name with size and date as the hint. A file not scanned clean
        is shown but cannot be picked, since nothing may use it yet (files 5.3.4)."""
        offset, window = options_window(None if ids else cursor, limit)
        rows = await self._files.options(who.tenant_id, who.team, search=search, offset=offset, limit=window, ids=ids)
        options = [
            {
                "id": r["id"],
                "label": r["name"],
                "hint": f"{_size(r['size'])} · {r['uploaded_at']:%d %b %Y}",
                "disabled": None if r["scan_status"] == "clean" else f"Not usable: scan is {r['scan_status']}",
            }
            for r in rows
        ]
        return options_page(options, offset, limit)

    async def list(
        self,
        who: Who,
        *,
        page: int,
        page_size: int,
        mine: bool = False,
        purpose: FilePurpose | None = None,
        ref_type: FileReferenceType | None = None,
        ref_id: str | None = None,
        search: str = "",
        uploaded_after: datetime | None = None,
        uploaded_before: datetime | None = None,
        view: str = "all",
        filters: Mapping[str, Sequence[str]] | None = None,
    ) -> dict[str, Any]:
        found = await self._files.list(
            who.tenant_id,
            who.team,
            page=page,
            page_size=page_size,
            uploaded_by=who.actor if mine else None,
            purpose=purpose,
            ref_type=ref_type,
            ref_id=ref_id,
            search=search,
            uploaded_after=uploaded_after,
            uploaded_before=uploaded_before,
            view=view,
            filters=filters,
            now=self._clock(),
        )
        pages = max(1, -(-found.total // page_size))
        return {
            "data": [self._row_detail(r, who) for r in found.rows],
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": found.total,
                "totalPages": pages,
                "hasNext": page < pages,
                "hasPrev": page > 1,
            },
            "facets": dict(found.facets),
            "viewCounts": dict(found.view_counts),
        }

    @staticmethod
    def _readable(row: FileRow) -> None:
        if row["status"] != "available":
            raise UploadStateError(f"{row['id']} is {row['status']}")
        if row["scan_status"] == "infected":
            raise QuarantinedError(f"{row['id']} is quarantined: {row['scan_detail']}")
        if row["scan_status"] != "clean":
            raise NotScannedError(f"{row['id']} scan is {row['scan_status']}")

    async def download_url(self, who: Who, file_id: str, *, expires_in: int | None = None) -> DownloadLink:
        row = await self._owned(who, file_id)
        self._readable(row)
        config = await self._config_for(who.tenant_id)
        ttl = expires_in if expires_in is not None else config.max_download_url_seconds
        if not 0 < ttl <= config.max_download_url_seconds:
            raise DownloadTtlError(f"download links last at most {config.max_download_url_seconds} seconds")
        store, proxy = await self._placement(row)
        if proxy:
            url = f"/v1/files/{file_id}/content"
        else:
            url = await asyncio.to_thread(store.presign_get, row["storage_key"], expires_in=ttl, filename=row["name"])
        return DownloadLink(url=url, expires_at=self._clock() + timedelta(seconds=ttl), ttl_seconds=ttl)

    async def open_content(self, who: Who, file_id: str) -> tuple[FileDetail, AsyncIterator[bytes]]:
        """A clean file's detail and its bytes as a stream, for the proxy download and service reads."""
        row = await self._owned(who, file_id)
        self._readable(row)
        store, _ = await self._placement(row)
        return self._detail(row, who), store.open_read(row["storage_key"])

    # ── delete ──

    def delete_blocked_by(self, row: FileRow) -> str | None:
        """Why the file cannot be deleted now, in words a person reads; None when it can. Delete refuses on the same
        rules, so the sheet and the 409 never disagree."""
        if row.references:
            n = len(row.references)
            return f"Used by {n} record{'s' if n != 1 else ''}. Remove it from each first."
        if row.hold is not None:
            return f"Under legal hold: {row.hold.reason}"
        retention = self._config.retention_class(row["retention_class_id"])
        delete_after = row["delete_after"]
        if (
            (retention.keep_until_end or retention.worm or row["immutable"])
            and delete_after is not None
            and self._clock().date() <= delete_after
        ):
            return f"Retained until {delete_after.isoformat()}."
        return None

    async def delete(self, who: Who, file_id: str) -> None:
        if not who.deletes:
            raise DeleteNotAllowedError("Your role in this team does not delete files.")
        row = await self._owned(who, file_id)
        if row.references:
            raise FileReferencedError(f"{file_id} is used by {len(row.references)} record(s)")
        if row.hold is not None:
            raise FileHeldError(f"{file_id} is under legal hold")
        if (blocked := self.delete_blocked_by(row)) is not None:
            raise FileRetainedError(f"{file_id}: {blocked}")
        store, _ = await self._placement(row)
        if await asyncio.to_thread(store.head, row["storage_key"]) is not None:
            await asyncio.to_thread(store.delete, row["storage_key"])
        payload = {"fileId": file_id, "digest": row["digest"], "name": row["name"], "deletedBy": who.actor}
        await self._files.remove(who.tenant_id, file_id, event={"team": row["team"], "payload": payload})

    async def bulk_delete(self, who: Who, ids: list[str]) -> dict[str, Any]:
        """Deletes each file the rules allow; one that cannot be deleted is skipped with the reason the sheet shows."""
        done: list[str] = []
        skipped: list[dict[str, str]] = []
        for file_id in ids:
            try:
                row = await self._owned(who, file_id)
            except FileMissingError:
                skipped.append({"id": file_id, "reason": "not found"})
                continue
            if (blocked := self.delete_blocked_by(row)) is not None:
                skipped.append({"id": file_id, "reason": blocked})
                continue
            await self.delete(who, file_id)
            done.append(file_id)
        return {"updated": done, "skipped": skipped}

    # ── legal hold ──

    async def set_legal_hold(self, who: Who, ids: list[str], *, hold: bool, reason: str) -> dict[str, Any]:
        """Places or releases holds on files of the caller's team; a file not found is skipped with its reason. The
        storage-level hold is set too, so a hold holds against a storage administrator (files 5.6.5)."""
        if who.team not in who.admin_teams:
            raise HoldRefusedError("only an admin of the file's team places or releases a legal hold")
        if not reason.strip():
            raise ReasonRequiredError("a legal hold needs a reason")
        done: list[str] = []
        skipped: list[dict[str, str]] = []
        for file_id in ids:
            try:
                row = await self._owned(who, file_id)
            except FileMissingError:
                skipped.append({"id": file_id, "reason": "not found"})
                continue
            if row["status"] != "available":
                skipped.append({"id": file_id, "reason": f"file is {row['status']}"})
                continue
            if hold == (row.hold is not None):
                skipped.append({"id": file_id, "reason": "already held" if hold else "not held"})
                continue
            store, _ = await self._placement(row)
            await asyncio.to_thread(store.set_legal_hold, row["storage_key"], hold)
            now = self._clock()
            if hold:
                hold_id = f"hold_{uuid.uuid4().hex}"
                await self._files.place_hold(who.tenant_id, file_id, hold_id, by=who.actor, at=now, reason=reason)
            else:
                assert row.hold is not None
                await self._files.release_hold(who.tenant_id, row.hold.id, by=who.actor, at=now, reason=reason)
            done.append(file_id)
        return {"updated": done, "skipped": skipped}

    # ── for other services ──

    async def write(
        self, who: Who, request: UploadRequest, chunks: AsyncIterable[bytes], *, idempotency_key: str | None = None
    ) -> CompletedUpload:
        """A file a service produces or receives (mail attachments, evidence, chat uploads it proxies): the same
        ticket, size, type and digest checks as a browser upload, without a signed URL (files F19). A retry with the
        same `idempotency_key` returns the file the first call stored."""
        ticket = await self.create_upload(who, request, idempotency_key=idempotency_key)
        row = await self._owned(who, ticket.file_id)
        if row["status"] == "available":
            return CompletedUpload(file=self._detail(row, who), deduplicated=False)
        seen = [0]
        # A retry whose first attempt stored the bytes and stopped before completing finds them in place.
        store, _ = await self._placement(row)
        with contextlib.suppress(ObjectExistsError):
            await store.put_stream(row["storage_key"], _counted(chunks, request.size, seen), content_type=request.mime)
        return await self.complete(who, ticket.file_id)

    async def add_reference(
        self, who: Who, file_id: str, *, type: FileReferenceType, ref_id: str, name: str, href: str | None, owner: str
    ) -> FileDetail:
        """Checks the file is clean and adds the reference in one call, so nothing reads the file between the check
        and the reference (files 5.3.4: pending, infected or failed answer 409)."""
        if not _REF_ID.fullmatch(ref_id):
            raise InvalidUploadError(f"invalid reference id {ref_id!r}")
        row = await self._owned(who, file_id)
        try:
            self._readable(row)
        except NotDownloadableError as error:
            raise UploadStateError(f"{file_id} cannot be attached: {error}") from error
        await self._files.add_reference(
            who.tenant_id,
            {
                "file_id": file_id,
                "ref_type": type,
                "ref_id": ref_id,
                "owner_service": owner,
                "name": name[:255],
                "href": href,
                "added_at": self._clock(),
                "blocked": None,
            },
        )
        return await self.get(who, file_id)

    async def remove_reference(self, who: Who, file_id: str, *, type: FileReferenceType, ref_id: str) -> FileDetail:
        await self._owned(who, file_id)
        await self._files.remove_reference(who.tenant_id, file_id, type, ref_id)
        return await self.get(who, file_id)

    async def record_scan(self, tenant: str, file_id: str, result: ScanResult) -> FileDetail:
        """The scan-result hook for an asynchronous scanner (ClamAV loop, Defender, GuardDuty). The tenant comes from
        the scanner's service token; the result is the only input."""
        row = await self._files.get(tenant, file_id)
        if row is None:
            raise FileMissingError(file_id)
        await self._files.update(
            tenant,
            file_id,
            {
                "scan_status": result.status,
                "scan_engine": result.engine,
                "scan_at": self._clock(),
                "scan_detail": result.detail,
            },
        )
        await self._files.set_blocked(
            tenant, file_id, f"Quarantined: {result.detail}" if result.status == "infected" else None
        )
        done = await self._files.get(tenant, file_id)
        assert done is not None
        return self._detail(done, None)


__all__ = [
    "DeleteRefusedError",
    "HoldRefusedError",
    "IdempotencyConflictError",
    "ReasonRequiredError",
    "ScanningMode",
    "TenantFiles",
    "Who",
]


def _size(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB" if n >= 1024 * 1024 else f"{max(1, round(n / 1024))} KB"
