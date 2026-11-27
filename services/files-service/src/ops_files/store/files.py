# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""files-service's tables and its door to them, under their own migration chain (alembic_version_files).

Portable SQL only (database portability D1, D5, D6): no JSON queried, bounded keys, plain inserts whose unique keys
carry the guarantees. Every transaction is `ops_store.isolation.isolated_tx` as `ops_files_tenant`, carrying the
caller's tenant and team from their token, and the database holds each table to them (migration files_0010):
team-owned tables to the team, the workspace's storage settings and upload keys to the tenant. Each read also filters
by tenant and, through `team_visible`, by team, so it seeks on its index."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar, NamedTuple, NotRequired, TypedDict

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.http import Out
from ops_service_kit.listing import ListParams
from ops_store import Guarantee, isolation
from ops_store.database import open_database, reachable
from ops_store.dialect import locked
from ops_store.listing import LISTED, ListPage, list_page, listed_rows
from ops_store.outbox import add as add_event
from ops_store.outbox import outbox_table
from ops_store.rows import one, rows
from ops_store.schema import TENANT_SCOPED, team_owned
from ops_store.search import contains
from ops_store.store import Store
from ops_store.team_scope import any_team, team_visible

# Listed in Files only when a filter asks for them: every email's text is stored so a workflow can read it, and
# listed beside the documents they would bury them. A run or case that used one still opens it by id.
LISTED_WHEN_ASKED: tuple[str, ...] = ("email_body", "knowledge_snapshot", "knowledge_rendition")
# Why the retention process reads past one tenant: it lists every tenant's released files past their date.
RETENTION_DUE = "background process: the retention process lists each tenant's released files past their date"

__all__ = [
    "ROLE",
    "SYSTEM_ROLE",
    "AsyncEngine",
    "FileChange",
    "FileDeleted",
    "FileDeletedPayload",
    "FileOut",
    "FileRow",
    "FilesStore",
    "HoldRow",
    "ListedFile",
    "NewReference",
    "NewUpload",
    "NewVersion",
    "OptionRow",
    "ReferenceOut",
    "UploadClaim",
    "UploadCompleted",
    "VersionOut",
    "engine_for",
    "metadata",
    "reachable",
]


class NewUpload(TypedDict):
    """The columns of a file row inserted when an upload is ticketed."""

    id: str
    tenant_id: str
    team: str
    name: str
    mime: str
    size: int
    purpose: str
    status: str
    scan_status: str
    sensitivity: str
    sensitivity_suggested: bool
    retention_class_id: str
    delete_after: NotRequired[date | None]
    immutable: bool
    storage_backend: str
    storage_container: str
    storage_key: str
    declared_size: int
    declared_digest: NotRequired[str | None]
    upload_expires_at: NotRequired[datetime | None]
    uploaded_by: str
    uploaded_at: datetime
    version_count: int


class UploadClaim(TypedDict):
    """An Idempotency-Key as indexed: hashes only, never the key or the request."""

    key_hash: str
    request_hash: str


class UploadCompleted(TypedDict):
    """The columns a completed upload sets: its proven type and digest, and the scan result when scanning ran inline."""

    digest: str
    mime: str
    sniffed_mime: str | None
    status: str
    upload_expires_at: None
    version_count: int
    scan_status: NotRequired[str]
    scan_engine: NotRequired[str]
    scan_at: NotRequired[datetime]
    scan_detail: NotRequired[str | None]


class NewVersion(TypedDict):
    """The first version row written with a completed upload."""

    version: int
    digest: str
    size: int
    storage_key: str
    uploaded_by: str
    uploaded_at: datetime
    current: bool


class SourceFile(TypedDict):
    """A file a watched folder found, as the check writes it: its source key and where it sits now."""

    key_hash: str
    source_id: str
    source_path: str
    name: str
    mime: str
    access_list: list[str] | None
    access_read_at: datetime
    # The watch that found it, so a full listing removes only its own watch's files, and the listing's marker for it.
    watch_id: NotRequired[str]
    marker: NotRequired[str | None]
    # When the source last changed it, as its listing said; kept on the version it writes.
    changed_at: NotRequired[datetime | None]


class HeldSource(NamedTuple):
    """What Files holds for one source file of a watch, as the listing compares it."""

    file_id: str
    marker: str | None
    tag: str | None
    gone_count: int
    name: str
    removed: bool


# What runs in a source version's own transaction once it is written: (connection, file id, the version's number, or
# None when the bytes matched the newest version).
Written = Callable[[AsyncConnection, str, "int | None"], Awaitable[None]]
# The connection a store write hands its callback, named here so code outside the store types it without importing
# the database driver.
InTx = AsyncConnection


class SourceVersion(TypedDict):
    """One version of a source file: its bytes, where they are stored, and the source's tag for them."""

    digest: str
    size: int
    storage_key: str
    source_tag: str | None
    at: datetime


class FileChange(TypedDict, total=False):
    """The columns `update` may set on a file row."""

    data: JsonValue
    read_as: str | None
    read_path: str | None
    purpose: str
    immutable: bool
    status: str
    delete_after: date | None
    scan_status: str
    scan_engine: str
    scan_at: datetime
    scan_detail: str | None


class NewReference(TypedDict):
    """A record of another service that uses a file."""

    file_id: str
    ref_type: str
    ref_id: str
    owner_service: str
    name: str
    href: str | None
    added_at: datetime
    blocked: str | None


class FileDeletedPayload(TypedDict):
    """The body of the file.deleted event, in its wire keys."""

    fileId: str
    digest: str | None
    name: str
    deletedBy: str


class FileDeleted(TypedDict):
    """A deletion's outbox event: the file's team and the file.deleted body."""

    team: str
    payload: FileDeletedPayload


# The role every transaction runs as; row-level security applies to it, not to the owner the service connects as.
ROLE = "ops_files_tenant"
# The role the outbox relay reads every tenant's events as (BYPASSRLS; granted the outbox alone).
SYSTEM_ROLE = "ops_files_system"

metadata = sa.MetaData()

files = sa.Table(
    "files",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("team", sa.String(64), nullable=False),
    # Display name only; it never reaches a storage key.
    sa.Column("name", sa.String(255), nullable=False, info=LISTED),
    sa.Column("mime", sa.String(127), nullable=False),
    sa.Column("sniffed_mime", sa.String(127)),
    sa.Column("size", sa.BigInteger, nullable=False, info=LISTED),
    sa.Column("digest", sa.String(64)),
    sa.Column("purpose", sa.String(32), nullable=False, info=LISTED),
    sa.Column("status", sa.String(16), nullable=False),  # uploading | available | rejected
    sa.Column("scan_status", sa.String(16), nullable=False, info=LISTED),  # pending | clean | infected | failed
    sa.Column("scan_engine", sa.String(64)),
    sa.Column("scan_at", sa.DateTime(timezone=True)),
    sa.Column("scan_detail", sa.String(500)),
    sa.Column("sensitivity", sa.String(16), nullable=False, info=LISTED),
    sa.Column("sensitivity_suggested", sa.Boolean, nullable=False),
    sa.Column("retention_class_id", sa.String(64), nullable=False),
    sa.Column("delete_after", sa.Date),
    sa.Column("immutable", sa.Boolean, nullable=False),
    sa.Column("storage_backend", sa.String(16), nullable=False),
    sa.Column("storage_container", sa.String(255), nullable=False),
    sa.Column("storage_key", sa.String(512), nullable=False),
    sa.Column("multipart_upload_id", sa.String(255)),
    sa.Column("declared_size", sa.BigInteger, nullable=False),
    sa.Column("declared_digest", sa.String(64)),
    sa.Column("upload_expires_at", sa.DateTime(timezone=True)),
    sa.Column("uploaded_by", sa.String(320), nullable=False),
    sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, info=LISTED),
    sa.Column("version_count", sa.Integer, nullable=False),
    # What was read from the file, recorded by the extract workflow; `read_as` and `read_path` repeat its
    # type and path as columns so the list filters and counts them in the query.
    sa.Column("data", sa.JSON),
    sa.Column("read_as", sa.String(64), info=LISTED),
    sa.Column("read_path", sa.String(16), info=LISTED),
    # Where the file came from: `upload` (its key is its own id) or `source` (its key is the hash of the connection
    # and the source's id for it, so a rename keeps the entry and the same bytes in two folders are two entries).
    sa.Column("source_scope", sa.String(16), nullable=False),
    sa.Column("source_key_hash", sa.String(64), nullable=False),
    sa.Column("source_id", sa.String(1024)),
    sa.Column("source_path", sa.String(1024)),
    # Set when the source no longer lists the file; the entry stays for its retention.
    sa.Column("removed_at", sa.DateTime(timezone=True)),
    # Who may see the file at its source, as last read: null when the source never said, [] when it listed nobody.
    sa.Column("access_list", sa.JSON),
    sa.Column("access_read_at", sa.DateTime(timezone=True)),
    sa.Column("watch_id", sa.String(64)),
    sa.Column("source_marker", sa.String(200)),
    # Checks in a row the source answered gone for this file; it is removed on the second.
    sa.Column("gone_count", sa.Integer, nullable=False, server_default="0"),
    # One entry per source file in a team: a second check that finds the same file adds a version, never a file.
    sa.Index("ux_files_source_key", "tenant_id", "team", "source_scope", "source_key_hash", unique=True),
    sa.Index("ix_files_team_status", "tenant_id", "team", "status", "uploaded_at"),
    sa.Index("ix_files_read_as", "tenant_id", "read_as", "team"),
    sa.Index("ix_files_delete_after", "tenant_id", "delete_after"),
    sa.Index("ix_files_name", "tenant_id", "name"),
    sa.Index("ix_files_purpose", "tenant_id", "purpose"),
    sa.Index("ix_files_scan_status", "tenant_id", "scan_status"),
    sa.Index("ix_files_sensitivity", "tenant_id", "sensitivity"),
    sa.Index("ix_files_uploaded_at", "tenant_id", "uploaded_at"),
    sa.Index("ix_files_read_path", "tenant_id", "read_path"),
    sa.Index("ix_files_size", "tenant_id", "size"),
    info={**TENANT_SCOPED, **team_owned("team")},
)

# Service events files-service reports (the outbox): a deleted file's file.deleted, which starts the system workflow
# that purges what documents-service read from it. Files calls no other service for that.
service_outbox = outbox_table(metadata, "files_outbox", info=TENANT_SCOPED)

# Dedupe guarantee: one available file per content digest per team. Two completions of the same bytes race to insert
# here; the loser's insert fails on the primary key and it returns the winner's file. Replaces a partial unique index
# on files, which MySQL 8 cannot express.
file_blobs = sa.Table(
    "file_blobs",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team", sa.String(64), primary_key=True),
    sa.Column("digest", sa.String(64), primary_key=True),
    sa.Column("file_id", sa.String(64), nullable=False),
    info={**TENANT_SCOPED, **team_owned("team")},
)

file_versions = sa.Table(
    "file_versions",
    metadata,
    sa.Column("file_id", sa.String(64), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("size", sa.BigInteger, nullable=False),
    sa.Column("storage_key", sa.String(512), nullable=False),
    sa.Column("uploaded_by", sa.String(320), nullable=False),
    sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("current", sa.Boolean, nullable=False),
    # The source's own version tag for this version (a SharePoint eTag), sent back so it can answer `unchanged`.
    sa.Column("source_tag", sa.String(200)),
    # When the source changed the bytes this version holds (its modified time), as its listing said; null for uploads.
    sa.Column("source_changed_at", sa.DateTime(timezone=True)),
    # Each version is scanned on its own: a new version stays unreadable until scanned while older ones still download.
    sa.Column("scan_status", sa.String(16), nullable=False),
    sa.Column("scan_at", sa.DateTime(timezone=True)),
    # The file's team, copied when the version is written, so the policy holds it without reading the file.
    sa.Column("team", sa.String(64), nullable=False),
    info={**TENANT_SCOPED, **team_owned("team")},
)

# Delete refuses while any row here names the file (files 5.6.6).
file_references = sa.Table(
    "file_references",
    metadata,
    sa.Column("file_id", sa.String(64), primary_key=True),
    sa.Column("ref_type", sa.String(32), primary_key=True),
    sa.Column("ref_id", sa.String(128), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("owner_service", sa.String(32), nullable=False),
    sa.Column("name", sa.String(255), nullable=False),
    sa.Column("href", sa.String(512)),
    sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("blocked", sa.String(500)),
    sa.Index("ix_file_references_owner", "tenant_id", "ref_type", "ref_id"),
    sa.Column("team", sa.String(64), nullable=False),
    info={**TENANT_SCOPED, **team_owned("team")},
)

# One row per Idempotency-Key a caller sent on an upload or a server write. The key is outside text, so only its
# SHA-256 (over tenant, team, caller and key) is the primary key (database portability D7); `request_hash` refuses
# the key reused for a different request. A plain insert on the key is what makes two concurrent retries one upload.
file_idempotency = sa.Table(
    "file_idempotency",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("key_hash", sa.String(64), primary_key=True),
    sa.Column("request_hash", sa.String(64), nullable=False),
    sa.Column("file_id", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_file_idempotency_file", "tenant_id", "file_id"),
    # Workspace-level: the key's hash already names the team.
    info=TENANT_SCOPED,
)

# A row per hold placed; release fills the release columns, so the history stays after a release.
file_legal_holds = sa.Table(
    "file_legal_holds",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("file_id", sa.String(64), nullable=False),
    sa.Column("placed_by", sa.String(320), nullable=False),
    sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("reason", sa.String(500), nullable=False),
    sa.Column("released_by", sa.String(320)),
    sa.Column("released_at", sa.DateTime(timezone=True)),
    sa.Column("release_reason", sa.String(500)),
    sa.Index("ix_file_legal_holds_file", "file_id", "released_at"),
    sa.Column("team", sa.String(64), nullable=False),
    info={**TENANT_SCOPED, **team_owned("team")},
)


class HoldRow(Out):
    id: str
    placed_by: str
    placed_at: datetime
    reason: str


class FileOut(Out):
    """A row of `files`, every column."""

    id: str
    tenant_id: str
    team: str
    name: str
    mime: str
    sniffed_mime: str | None
    size: int
    digest: str | None
    purpose: str
    status: str
    scan_status: str
    scan_engine: str | None
    scan_at: datetime | None
    scan_detail: str | None
    sensitivity: str
    sensitivity_suggested: bool
    retention_class_id: str
    delete_after: date | None
    immutable: bool
    storage_backend: str
    storage_container: str
    storage_key: str
    multipart_upload_id: str | None
    declared_size: int
    declared_digest: str | None
    upload_expires_at: datetime | None
    uploaded_by: str
    uploaded_at: datetime
    version_count: int
    data: JsonValue
    read_as: str | None
    read_path: str | None
    source_scope: str = "upload"
    source_key_hash: str = ""
    source_id: str | None = None
    source_path: str | None = None
    removed_at: datetime | None = None
    access_list: list[str] | None = None
    access_read_at: datetime | None = None
    watch_id: str | None = None
    source_marker: str | None = None
    gone_count: int = 0


class ListedFile(FileOut):
    """A list row: the file with its reference count and its open hold's who, when and why."""

    reference_count: int
    hold_by: str | None
    hold_at: datetime | None
    hold_reason: str | None


class VersionOut(Out):
    file_id: str
    version: int
    tenant_id: str
    digest: str
    size: int
    storage_key: str
    uploaded_by: str
    uploaded_at: datetime
    current: bool
    team: str
    source_tag: str | None = None
    source_changed_at: datetime | None = None
    scan_status: str = "pending"
    scan_at: datetime | None = None


class ReferenceOut(Out):
    file_id: str
    ref_type: str
    ref_id: str
    tenant_id: str
    owner_service: str
    name: str
    href: str | None
    added_at: datetime
    blocked: str | None
    team: str


class OptionRow(Out):
    """A picker's row."""

    id: str
    name: str
    size: int
    scan_status: str
    uploaded_at: datetime


class FileRow(Out):
    """One file with the rows the API shows beside it."""

    file: FileOut
    versions: list[VersionOut]
    references: list[ReferenceOut]
    hold: HoldRow | None
    # The name of the watch that brought the file in; None for uploads and once the watch is deleted.
    watch_name: str | None = None


VIEWS = ("all", "quarantined", "legal_hold", "unreferenced", "expiring")
# The list's filters, each also a facet it counts, by the query key the console sends.
FACETS: Mapping[str, sa.Column[Any]] = {
    "purpose": files.c.purpose,
    "scan": files.c.scan_status,
    "sensitivity": files.c.sensitivity,
    "readAs": files.c.read_as,
    "readPath": files.c.read_path,
}


def _team_of(file_id: str) -> Any:
    """The file's team; another team's file is not visible, so a row naming it has no team and is refused."""
    return sa.select(files.c.team).where(files.c.id == file_id, team_visible(files)).scalar_subquery()


def engine_for(url: str) -> AsyncEngine:
    return open_database(url)


class FilesStore(Store):
    role = ROLE
    # Completion claims the digest and marks the file available in one transaction (file_blobs above).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    # ── reads ──

    async def get(self, file_id: str) -> FileRow | None:
        tenant = isolation.tenant()
        async with self.tx() as c:
            return await self._get(c, tenant, file_id)

    async def _get(self, c: AsyncConnection, tenant: str, file_id: str) -> FileRow | None:
        found = await one(
            c, sa.select(files).where(files.c.tenant_id == tenant, files.c.id == file_id, team_visible(files)), FileOut
        )
        if found is None:
            return None
        v, r, h = file_versions, file_references, file_legal_holds
        versions = sa.select(v).where(v.c.tenant_id == tenant, v.c.file_id == file_id, team_visible(v))
        references = sa.select(r).where(r.c.tenant_id == tenant, r.c.file_id == file_id, team_visible(r))
        hold = sa.select(h.c.id, h.c.placed_by, h.c.placed_at, h.c.reason).where(
            h.c.tenant_id == tenant, h.c.file_id == file_id, h.c.released_at.is_(None), team_visible(h)
        )
        watch_name = None
        if found.watch_id is not None:
            # file_watches is defined in .watches, which imports this module; looked up by name to keep one direction.
            w = metadata.tables["file_watches"]
            q = sa.select(w.c.name).where(w.c.tenant_id == tenant, w.c.id == found.watch_id, team_visible(w))
            watch_name = (await c.execute(q)).scalar_one_or_none()
        return FileRow(
            file=found,
            versions=await rows(c, versions.order_by(v.c.version), VersionOut),
            references=await rows(c, references.order_by(r.c.added_at), ReferenceOut),
            hold=next(iter(await rows(c, hold.limit(1), HoldRow)), None),
            watch_name=watch_name,
        )

    async def options(
        self, team: str, *, search: str, offset: int, limit: int, ids: list[str] | None
    ) -> list[OptionRow]:
        """A picker's page of one team's available files, newest first: searched by name in the query, or the given
        ids. Returns id, name, size, scan status and upload time."""
        tenant = isolation.tenant()
        where: list[sa.ColumnElement[bool]] = [
            files.c.tenant_id == tenant,
            files.c.team == team,
            files.c.status == "available",
            team_visible(files),
        ]
        if ids is not None:
            where.append(files.c.id.in_(ids))
        elif search.strip():
            where.append(contains(files.c.name, search))
        cols = (files.c.id, files.c.name, files.c.size, files.c.scan_status, files.c.uploaded_at)
        q = sa.select(*cols).where(*where).order_by(files.c.uploaded_at.desc(), files.c.id)
        async with self.tx() as c:
            return await rows(c, q if ids is not None else q.limit(limit).offset(offset), OptionRow)

    async def list(
        self,
        team: str,
        params: ListParams,
        *,
        purposes: Sequence[str],
        uploaded_by: str | None = None,
        ref_type: str | None = None,
        ref_id: str | None = None,
        uploaded_after: datetime | None = None,
        uploaded_before: datetime | None = None,
        view: str = "all",
        now: datetime | None = None,
    ) -> tuple[ListPage, dict[str, int]]:
        """Available files of one team on the shared list contract, newest first, and the count of each view the Files
        page offers under the same search and filters, all in one transaction. `purposes` is every purpose: a list that
        names no purpose and no record keeps to those not listed only when asked for, as a purpose filter, so the
        purpose facet, which leaves its own filter out, still counts them and the filter offers them."""
        tenant = isolation.tenant()
        at = now or datetime.now(UTC)
        base: list[sa.ColumnElement[bool]] = [
            files.c.tenant_id == tenant,
            files.c.team == team,
            files.c.status == "available",
            team_visible(files),
        ]
        if uploaded_by is not None:
            base.append(files.c.uploaded_by == uploaded_by)
        if ref_type is not None or ref_id is not None:
            refs = sa.select(file_references.c.file_id).where(
                file_references.c.tenant_id == tenant, team_visible(file_references)
            )
            if ref_type is not None:
                refs = refs.where(file_references.c.ref_type == ref_type)
            if ref_id is not None:
                refs = refs.where(file_references.c.ref_id == ref_id)
            base.append(files.c.id.in_(refs))
        if uploaded_after is not None:
            base.append(files.c.uploaded_at >= uploaded_after)
        if uploaded_before is not None:
            base.append(files.c.uploaded_at < uploaded_before)
        asked = bool(params.filters.get("purpose")) or ref_type is not None or ref_id is not None
        if not asked:
            shown = [p for p in purposes if p not in LISTED_WHEN_ASKED]
            params = params.model_copy(update={"filters": {**params.filters, "purpose": shown}})
        search = (files.c.name, files.c.uploaded_by, files.c.digest)
        query = sa.select(files, self._reference_count(), *self._hold_columns()).where(*base)
        async with self.tx() as c:
            page = await list_page(
                c,
                query.where(self._in_view(view, tenant, at)),
                params,
                search=search,
                sortable={
                    "name": files.c.name,
                    "uploadedAt": files.c.uploaded_at,
                    "size": files.c.size,
                    "scan": files.c.scan_status,
                    "purpose": files.c.purpose,
                },
                default_sort=files.c.uploaded_at.desc(),
                filters=FACETS,
                facets=FACETS,
            )
            # The views' counts under the page's own search and filters: the same rows list_page counted, by view.
            rows = listed_rows(
                sa.select(sa.func.count()).select_from(files).where(*base), params, search=search, filters=FACETS
            )
            counts: dict[str, int] = {}
            for v in VIEWS:
                counts[v] = int((await c.execute(rows.where(self._in_view(v, tenant, at)))).scalar_one())
        return page, counts

    @staticmethod
    def _in_view(view: str, tenant: str, now: datetime) -> sa.ColumnElement[bool]:
        """The views the Files page offers, as the console mock defines them: quarantined scans, files under a hold,
        files nothing has used for 30 days, and files whose retention ends within 30 days and no hold keeps."""
        held = sa.exists().where(
            file_legal_holds.c.tenant_id == tenant,
            file_legal_holds.c.file_id == files.c.id,
            file_legal_holds.c.released_at.is_(None),
            team_visible(file_legal_holds),
        )
        used = sa.exists().where(
            file_references.c.tenant_id == tenant,
            file_references.c.file_id == files.c.id,
            team_visible(file_references),
        )
        if view == "quarantined":
            return files.c.scan_status.in_(("infected", "failed"))
        if view == "legal_hold":
            return held
        if view == "unreferenced":
            return sa.and_(~used, files.c.uploaded_at < now - timedelta(days=30))
        if view == "expiring":
            soon = (now + timedelta(days=30)).date()
            return sa.and_(~held, files.c.delete_after.is_not(None), files.c.delete_after <= soon)
        return sa.true()

    @staticmethod
    def _hold_columns() -> list[sa.Label[Any]]:
        """The open hold's who, when and why, for a list row."""

        def col(c: sa.Column[Any], name: str) -> sa.Label[Any]:
            return (
                sa.select(c)
                .where(
                    file_legal_holds.c.tenant_id == files.c.tenant_id,
                    file_legal_holds.c.file_id == files.c.id,
                    file_legal_holds.c.released_at.is_(None),
                    team_visible(file_legal_holds),
                )
                .limit(1)
                .scalar_subquery()
                .label(name)
            )

        return [
            col(file_legal_holds.c.placed_by, "hold_by"),
            col(file_legal_holds.c.placed_at, "hold_at"),
            col(file_legal_holds.c.reason, "hold_reason"),
        ]

    @staticmethod
    def _reference_count() -> sa.Label[int]:
        return (
            sa.select(sa.func.count())
            .where(
                file_references.c.tenant_id == files.c.tenant_id,
                file_references.c.file_id == files.c.id,
                team_visible(file_references),
            )
            .scalar_subquery()
            .label("reference_count")
        )

    # ── writes ──

    async def insert_upload(
        self, values: NewUpload, *, idempotency: UploadClaim | None = None
    ) -> tuple[str, str] | None:
        """Inserts an upload, and with `idempotency` ({key_hash, request_hash}) claims the key for it in the same
        transaction. When another upload already holds the key, nothing is written and (its file id, its request
        hash) is returned."""
        tenant = str(values["tenant_id"])
        async with self.tx() as c:
            try:
                async with self.attempt(c):
                    if idempotency is not None:
                        await c.execute(
                            sa.insert(file_idempotency).values(
                                tenant_id=tenant,
                                key_hash=idempotency["key_hash"],
                                request_hash=idempotency["request_hash"],
                                file_id=values["id"],
                                created_at=values["uploaded_at"],
                            )
                        )
                    await c.execute(
                        sa.insert(files).values(source_scope="upload", source_key_hash=values["id"], **values)
                    )
            except IntegrityError:
                if idempotency is None:
                    raise
                held = await self._idempotent(c, idempotency["key_hash"])
                if held is None:
                    raise
                return held
        return None

    async def idempotent_upload(self, key_hash: str) -> tuple[str, str] | None:
        """(file id, request hash) an Idempotency-Key already holds, or None."""
        async with self.tx() as c:
            return await self._idempotent(c, key_hash)

    @staticmethod
    async def _idempotent(c: AsyncConnection, key_hash: str) -> tuple[str, str] | None:
        t = file_idempotency
        q = sa.select(t.c.file_id, t.c.request_hash).where(
            t.c.tenant_id == isolation.tenant(), t.c.key_hash == key_hash
        )
        row = (await c.execute(q)).first()
        return (str(row[0]), str(row[1])) if row is not None else None

    async def repoint_idempotency(self, from_file: str, to_file: str) -> None:
        """A deduplicated upload's keys now name the file it was folded into, so a retry finds that file."""
        tenant = isolation.tenant()
        async with self.tx() as c:
            await c.execute(
                sa.update(file_idempotency)
                .where(file_idempotency.c.tenant_id == tenant, file_idempotency.c.file_id == from_file)
                .values(file_id=to_file)
            )

    async def update(self, file_id: str, values: FileChange) -> None:
        tenant = isolation.tenant()
        async with self.tx() as c:
            await c.execute(sa.update(files).where(files.c.tenant_id == tenant, files.c.id == file_id).values(**values))

    async def make_available(self, file_id: str, values: UploadCompleted, version: NewVersion) -> str | None:
        """Marks an upload available and claims its digest for the team in one transaction. When another file of the
        team already holds the digest, nothing is written and that file's id is returned."""
        tenant = isolation.tenant()
        async with self.tx() as c:
            row = await self._get(c, tenant, file_id)
            assert row is not None
            team = row.file.team
            try:
                async with self.attempt(c):
                    await c.execute(
                        sa.insert(file_blobs).values(
                            tenant_id=tenant, team=team, digest=values["digest"], file_id=file_id
                        )
                    )
                    await c.execute(
                        sa.update(files)
                        .where(files.c.tenant_id == tenant, files.c.id == file_id, files.c.status == "uploading")
                        .values(**values)
                    )
                    await c.execute(
                        sa.insert(file_versions).values(
                            file_id=file_id,
                            tenant_id=tenant,
                            team=team,
                            scan_status=values.get("scan_status", row.file.scan_status),
                            **version,
                        )
                    )
            except IntegrityError:
                b = file_blobs
                held = sa.select(b.c.file_id).where(
                    b.c.tenant_id == tenant, b.c.team == team, b.c.digest == values["digest"], team_visible(b)
                )
                return (await c.execute(held)).scalar_one()
        return None

    async def set_version_scan(self, file_id: str, version: int, status: str, at: datetime) -> None:
        """Records one version's scan, so that version alone becomes readable (or stays refused)."""
        v = file_versions
        async with self.tx() as c:
            await c.execute(
                sa.update(v)
                .where(v.c.tenant_id == isolation.tenant(), v.c.file_id == file_id, v.c.version == version)
                .values(scan_status=status, scan_at=at)
            )

    async def put_source_version(
        self,
        team: str,
        new_file: NewUpload,
        found: SourceFile,
        version: SourceVersion,
        *,
        then: Written | None = None,
    ) -> tuple[str, int | None]:
        """Writes what a check fetched for one source file: found by its source key only, never by its bytes, so two
        folders holding the same bytes are two entries. Bytes the same as the newest version write no version and
        answer (file id, None); else the next version is written unscanned and answered with its number. The entry's
        name, path and access list follow the source either way. `new_file` is the row written when the key is new.
        `then(c, file_id, number)` runs in the same transaction (a watch writes the version's event there), so what it
        raises writes nothing."""
        tenant = isolation.tenant()
        f, v = files, file_versions
        where = (f.c.tenant_id == tenant, f.c.team == team, f.c.source_scope == "source",
                 f.c.source_key_hash == found["key_hash"])  # fmt: skip
        follows = {
            "name": found["name"],
            "source_id": found["source_id"],
            "source_path": found["source_path"],
            "access_list": found["access_list"],
            "access_read_at": found["access_read_at"],
            "removed_at": None,
            "gone_count": 0,
        }
        if "watch_id" in found:
            follows["watch_id"] = found["watch_id"]
        if "marker" in found:
            follows["source_marker"] = found["marker"]
        newest = None
        async with self.tx() as c:
            file_id = (await c.execute(sa.select(f.c.id).where(*where))).scalar_one_or_none()
            if file_id is None:
                row = {**new_file, **follows, "source_scope": "source", "source_key_hash": found["key_hash"],
                       "mime": found["mime"], "status": "available", "digest": version["digest"],
                       "size": version["size"], "declared_size": version["size"], "version_count": 0}  # fmt: skip
                try:
                    async with self.attempt(c):
                        await c.execute(sa.insert(f).values(**row))
                    file_id = str(new_file["id"])
                except IntegrityError:
                    # Two checks found the same new file at once: the other wrote the entry; this one adds to it.
                    file_id = (await c.execute(sa.select(f.c.id).where(*where))).scalar_one()
            if file_id != str(new_file["id"]):
                q = locked(sa.select(f.c.id).where(*where), f)
                await c.execute(q)
                q = sa.select(v.c.version, v.c.digest).where(v.c.tenant_id == tenant, v.c.file_id == file_id)
                newest = (await c.execute(q.order_by(v.c.version.desc()).limit(1))).first()
                await c.execute(sa.update(f).where(*where).values(**follows))
                if newest is not None and newest.digest == version["digest"]:
                    if then is not None:
                        await then(c, file_id, None)
                    return file_id, None
            number = (newest.version if newest is not None else 0) + 1
            await c.execute(sa.update(v).where(v.c.tenant_id == tenant, v.c.file_id == file_id).values(current=False))
            await c.execute(
                sa.insert(v).values(
                    file_id=file_id, version=number, tenant_id=tenant, team=team, digest=version["digest"],
                    size=version["size"], storage_key=version["storage_key"], source_tag=version["source_tag"],
                    source_changed_at=found.get("changed_at"),
                    uploaded_by=new_file["uploaded_by"], uploaded_at=version["at"], current=True,
                    scan_status="pending",
                )
            )  # fmt: skip
            await c.execute(
                sa.update(f)
                .where(*where)
                .values(
                    version_count=number,
                    digest=version["digest"],
                    size=version["size"],
                    storage_key=version["storage_key"],
                )
            )
            if then is not None:
                await then(c, file_id, number)
        return file_id, number

    async def held_sources(self, team: str, watch_id: str) -> dict[str, HeldSource]:
        """Every source file this watch brought in, by the source's id, as the listing compares it."""
        f, v = files, file_versions
        tag = (
            sa.select(v.c.source_tag)
            .where(v.c.tenant_id == f.c.tenant_id, v.c.file_id == f.c.id, v.c.current == sa.true())
            .scalar_subquery()
        )
        q = sa.select(f.c.id, f.c.source_id, f.c.source_marker, tag, f.c.gone_count, f.c.name, f.c.removed_at).where(
            f.c.tenant_id == isolation.tenant(), f.c.team == team, f.c.source_scope == "source",
            f.c.watch_id == watch_id, team_visible(f),
        )  # fmt: skip
        async with self.tx() as c:
            return {
                str(r[1]): HeldSource(str(r[0]), r[2], r[3], int(r[4] or 0), str(r[5]), r[6] is not None)
                for r in await c.execute(q)
            }

    async def mark_source(self, file_id: str, *, marker: str | None, gone_count: int | None = None) -> None:
        """Keeps the listing's marker for a source file (or how many checks in a row found it gone)."""
        q = sa.update(files).where(files.c.tenant_id == isolation.tenant(), files.c.id == file_id)
        async with self.tx() as c:
            await c.execute(q.values(source_marker=marker) if gone_count is None else q.values(gone_count=gone_count))

    async def remove_sources(
        self, file_ids: Sequence[str], at: datetime, *, then: Callable[[AsyncConnection], Awaitable[None]] | None = None
    ) -> None:
        """Marks source files removed at the source; each entry stays for its retention. `then(c)` runs in the same
        transaction (a watch writes the removals' events there)."""
        if not file_ids:
            return
        f = files
        async with self.tx() as c:
            await c.execute(
                sa.update(f)
                .where(f.c.tenant_id == isolation.tenant(), f.c.id.in_(list(file_ids)), f.c.removed_at.is_(None))
                .values(removed_at=at)
            )
            if then is not None:
                await then(c)

    async def released_due(self, purposes: Sequence[str], today: date) -> list[tuple[str, str, str]]:
        """(tenant, team, file id) of every available file of `purposes` whose date has passed; whether each may go
        (references, a hold) is the delete's own check, made as its tenant."""
        if not purposes:
            return []
        q = sa.select(files.c.tenant_id, files.c.team, files.c.id).where(
            any_team(files, RETENTION_DUE),
            files.c.purpose.in_(list(purposes)),
            files.c.status == "available",
            files.c.delete_after.is_not(None),
            files.c.delete_after < today,
        )
        async with isolation.system_tx(self.engine, RETENTION_DUE, role=SYSTEM_ROLE) as c:
            return [(str(r[0]), str(r[1]), str(r[2])) for r in await c.execute(q)]

    async def remove(self, file_id: str, *, event: FileDeleted | None = None) -> None:
        """Deletes the file's rows; the digest is free again for its team. Hold history stays. `event` (team and
        payload) is written to the outbox in the same transaction, so the deletion and its file.deleted event commit
        together and a relay delivers it however long agents-service is down."""
        tenant = isolation.tenant()
        async with self.tx() as c:
            if event is not None:
                await add_event(
                    c,
                    service_outbox,
                    tenant_id=tenant,
                    team_id=event["team"],
                    name="file.deleted",
                    key=file_id,
                    payload=dict(event["payload"]),
                )
            await c.execute(
                sa.delete(file_blobs).where(file_blobs.c.tenant_id == tenant, file_blobs.c.file_id == file_id)
            )
            await c.execute(
                sa.delete(file_versions).where(file_versions.c.tenant_id == tenant, file_versions.c.file_id == file_id)
            )
            await c.execute(
                sa.delete(file_references).where(
                    file_references.c.tenant_id == tenant, file_references.c.file_id == file_id
                )
            )
            await c.execute(sa.delete(files).where(files.c.tenant_id == tenant, files.c.id == file_id))

    async def place_hold(self, file_id: str, hold_id: str, *, by: str, at: datetime, reason: str) -> None:
        tenant = isolation.tenant()
        async with self.tx() as c:
            await c.execute(
                sa.insert(file_legal_holds).values(
                    id=hold_id,
                    tenant_id=tenant,
                    file_id=file_id,
                    team=_team_of(file_id),
                    placed_by=by,
                    placed_at=at,
                    reason=reason,
                )
            )

    async def release_hold(self, hold_id: str, *, by: str, at: datetime, reason: str) -> None:
        tenant = isolation.tenant()
        async with self.tx() as c:
            await c.execute(
                sa.update(file_legal_holds)
                .where(file_legal_holds.c.tenant_id == tenant, file_legal_holds.c.id == hold_id)
                .values(released_by=by, released_at=at, release_reason=reason)
            )

    async def add_reference(self, values: NewReference) -> bool:
        """False when the file already has this reference."""
        tenant = isolation.tenant()
        team = _team_of(values["file_id"])
        async with self.tx() as c:
            try:
                async with self.attempt(c):
                    await c.execute(sa.insert(file_references).values(tenant_id=tenant, team=team, **values))
            except IntegrityError:
                return False
        return True

    async def remove_reference(self, file_id: str, ref_type: str, ref_id: str) -> None:
        tenant = isolation.tenant()
        async with self.tx() as c:
            await c.execute(
                sa.delete(file_references).where(
                    file_references.c.tenant_id == tenant,
                    file_references.c.file_id == file_id,
                    file_references.c.ref_type == ref_type,
                    file_references.c.ref_id == ref_id,
                )
            )

    async def set_blocked(self, file_id: str, blocked: str | None) -> None:
        tenant = isolation.tenant()
        async with self.tx() as c:
            await c.execute(
                sa.update(file_references)
                .where(file_references.c.tenant_id == tenant, file_references.c.file_id == file_id)
                .values(blocked=blocked)
            )
