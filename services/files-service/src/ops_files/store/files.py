# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""files-service's tables and its door to them, under their own migration chain (alembic_version_files).

Portable SQL only (database portability D1, D5, D6): no JSON queried, bounded keys, plain inserts whose unique keys
carry the guarantees. Every statement filters on the tenant it is given, which comes from the caller's token; team
scoping is the use-case layer's, on top of it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store import Guarantee
from ops_store.database import open_database
from ops_store.outbox import add as add_event
from ops_store.outbox import outbox_table
from ops_store.search import contains

__all__ = ["AsyncEngine", "FileRow", "FilesStore", "HoldRow", "Page", "engine_for", "metadata", "reachable"]

metadata = sa.MetaData()

files = sa.Table(
    "files",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("team", sa.String(64), nullable=False),
    # Display name only; it never reaches a storage key.
    sa.Column("name", sa.String(255), nullable=False),
    sa.Column("mime", sa.String(127), nullable=False),
    sa.Column("sniffed_mime", sa.String(127)),
    sa.Column("size", sa.BigInteger, nullable=False),
    sa.Column("digest", sa.String(64)),
    sa.Column("purpose", sa.String(32), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),  # uploading | available | rejected
    sa.Column("scan_status", sa.String(16), nullable=False),  # pending | clean | infected | failed
    sa.Column("scan_engine", sa.String(64)),
    sa.Column("scan_at", sa.DateTime(timezone=True)),
    sa.Column("scan_detail", sa.String(500)),
    sa.Column("sensitivity", sa.String(16), nullable=False),
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
    sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("version_count", sa.Integer, nullable=False),
    # What was read from the file (c-250), recorded by the extract workflow; `read_as` and `read_path` repeat its
    # type and path as columns so the list filters and counts them in the query.
    sa.Column("data", sa.JSON),
    sa.Column("read_as", sa.String(64)),
    sa.Column("read_path", sa.String(16)),
    sa.Index("ix_files_team_status", "tenant_id", "team", "status", "uploaded_at"),
    sa.Index("ix_files_read_as", "tenant_id", "team", "read_as"),
    sa.Index("ix_files_delete_after", "tenant_id", "delete_after"),
)

# Service events files-service reports (c-258's outbox): a deleted file's file.deleted, which starts the system workflow
# that purges what documents-service read from it. Files calls no other service for that.
service_outbox = outbox_table(metadata, "files_outbox")

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
)


@dataclass(frozen=True)
class HoldRow:
    id: str
    placed_by: str
    placed_at: datetime
    reason: str


@dataclass(frozen=True)
class FileRow:
    """One file with the rows the API shows beside it."""

    file: Mapping[str, Any]
    versions: Sequence[Mapping[str, Any]]
    references: Sequence[Mapping[str, Any]]
    hold: HoldRow | None

    def __getitem__(self, column: str) -> Any:
        return self.file[column]


@dataclass(frozen=True)
class Page:
    rows: Sequence[Mapping[str, Any]]
    total: int
    view_counts: Mapping[str, int] = field(default_factory=dict[str, int])
    facets: Mapping[str, Mapping[str, int]] = field(default_factory=dict[str, Mapping[str, int]])


VIEWS = ("all", "quarantined", "legal_hold", "unreferenced", "expiring")


def engine_for(url: str) -> AsyncEngine:
    return open_database(url)


async def reachable(engine: AsyncEngine) -> bool:
    """Whether the database answers; health says degraded when it does not."""
    try:
        async with engine.connect() as c:
            await c.execute(sa.text("SELECT 1"))
    except Exception:
        return False
    return True


class FilesStore:
    # Completion claims the digest and marks the file available in one transaction (file_blobs above).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    # ── reads ──

    async def get(self, tenant: str, file_id: str) -> FileRow | None:
        async with self.engine.connect() as c:
            return await self._get(c, tenant, file_id)

    async def _get(self, c: AsyncConnection, tenant: str, file_id: str) -> FileRow | None:
        row = (
            (await c.execute(sa.select(files).where(files.c.tenant_id == tenant, files.c.id == file_id)))
            .mappings()
            .first()
        )
        if row is None:
            return None
        versions = (
            (
                await c.execute(
                    sa.select(file_versions)
                    .where(file_versions.c.tenant_id == tenant, file_versions.c.file_id == file_id)
                    .order_by(file_versions.c.version)
                )
            )
            .mappings()
            .all()
        )
        references = (
            (
                await c.execute(
                    sa.select(file_references)
                    .where(file_references.c.tenant_id == tenant, file_references.c.file_id == file_id)
                    .order_by(file_references.c.added_at)
                )
            )
            .mappings()
            .all()
        )
        hold = (
            (
                await c.execute(
                    sa.select(file_legal_holds).where(
                        file_legal_holds.c.tenant_id == tenant,
                        file_legal_holds.c.file_id == file_id,
                        file_legal_holds.c.released_at.is_(None),
                    )
                )
            )
            .mappings()
            .first()
        )
        return FileRow(
            file=dict(row),
            versions=[dict(v) for v in versions],
            references=[dict(r) for r in references],
            hold=HoldRow(hold["id"], hold["placed_by"], hold["placed_at"], hold["reason"]) if hold else None,
        )

    async def options(
        self, tenant: str, team: str, *, search: str, offset: int, limit: int, ids: list[str] | None
    ) -> list[dict[str, Any]]:
        """A picker's page of one team's available files, newest first: searched by name in the query, or the given
        ids. Returns id, name, size, scan status and upload time."""
        where: list[sa.ColumnElement[bool]] = [
            files.c.tenant_id == tenant,
            files.c.team == team,
            files.c.status == "available",
        ]
        if ids is not None:
            where.append(files.c.id.in_(ids))
        elif search.strip():
            where.append(contains(files.c.name, search))
        cols = (files.c.id, files.c.name, files.c.size, files.c.scan_status, files.c.uploaded_at)
        q = sa.select(*cols).where(*where).order_by(files.c.uploaded_at.desc(), files.c.id)
        async with self.engine.connect() as c:
            rows = await c.execute(q if ids is not None else q.limit(limit).offset(offset))
            return [dict(r) for r in rows.mappings().all()]

    async def list(
        self,
        tenant: str,
        team: str,
        *,
        page: int,
        page_size: int,
        uploaded_by: str | None = None,
        purpose: str | None = None,
        ref_type: str | None = None,
        ref_id: str | None = None,
        search: str = "",
        uploaded_after: datetime | None = None,
        uploaded_before: datetime | None = None,
        view: str = "all",
        filters: Mapping[str, Sequence[str]] | None = None,
        now: datetime | None = None,
    ) -> Page:
        """Available files of one team, newest first. Search, the uploaded-since date, the view and the facet filters
        run in the query; `view_counts` and `facets` are grouped counts under the same search and date, so no page
        counts rows it did not load."""
        at = now or datetime.now(UTC)
        base: list[sa.ColumnElement[bool]] = [
            files.c.tenant_id == tenant,
            files.c.team == team,
            files.c.status == "available",
        ]
        if uploaded_by is not None:
            base.append(files.c.uploaded_by == uploaded_by)
        if purpose is not None:
            base.append(files.c.purpose == purpose)
        if ref_type is not None or ref_id is not None:
            refs = sa.select(file_references.c.file_id).where(file_references.c.tenant_id == tenant)
            if ref_type is not None:
                refs = refs.where(file_references.c.ref_type == ref_type)
            if ref_id is not None:
                refs = refs.where(file_references.c.ref_id == ref_id)
            base.append(files.c.id.in_(refs))
        if search.strip():
            base.append(sa.or_(*(contains(col, search) for col in (files.c.name, files.c.uploaded_by, files.c.digest))))
        if uploaded_after is not None:
            base.append(files.c.uploaded_at >= uploaded_after)
        if uploaded_before is not None:
            base.append(files.c.uploaded_at < uploaded_before)
        facet_cols = {
            "purpose": files.c.purpose,
            "scan": files.c.scan_status,
            "sensitivity": files.c.sensitivity,
            "readAs": files.c.read_as,
            "readPath": files.c.read_path,
        }
        chosen = {k: list(v) for k, v in (filters or {}).items() if k in facet_cols and v}

        def facet_where(skip: str | None = None) -> list[sa.ColumnElement[bool]]:
            return [facet_cols[k].in_(v) for k, v in chosen.items() if k != skip]

        where = [*base, *facet_where(), self._in_view(view, tenant, at)]
        async with self.engine.connect() as c:
            total = int((await c.execute(sa.select(sa.func.count()).select_from(files).where(*where))).scalar_one())
            rows = (
                (
                    await c.execute(
                        sa.select(files, self._reference_count(), *self._hold_columns())
                        .where(*where)
                        .order_by(files.c.uploaded_at.desc(), files.c.id)
                        .limit(page_size)
                        .offset((page - 1) * page_size)
                    )
                )
                .mappings()
                .all()
            )
            counts: dict[str, int] = {}
            for v in VIEWS:
                in_view = self._in_view(v, tenant, at)
                q = sa.select(sa.func.count()).select_from(files).where(*base, *facet_where(), in_view)
                counts[v] = int((await c.execute(q)).scalar_one())
            facets: dict[str, dict[str, int]] = {}
            for key, col in facet_cols.items():
                q = (
                    sa.select(col, sa.func.count())
                    .where(*base, *facet_where(key), self._in_view(view, tenant, at))
                    .group_by(col)
                )
                facets[key] = {str(k): int(n) for k, n in (await c.execute(q)).all()}
        return Page(rows=[dict(r) for r in rows], total=total, view_counts=counts, facets=facets)

    @staticmethod
    def _in_view(view: str, tenant: str, now: datetime) -> sa.ColumnElement[bool]:
        """The views the Files page offers, as the console mock defines them: quarantined scans, files under a hold,
        files nothing has used for 30 days, and files whose retention ends within 30 days and no hold keeps."""
        held = sa.exists().where(
            file_legal_holds.c.tenant_id == tenant,
            file_legal_holds.c.file_id == files.c.id,
            file_legal_holds.c.released_at.is_(None),
        )
        used = sa.exists().where(file_references.c.tenant_id == tenant, file_references.c.file_id == files.c.id)
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
            .where(file_references.c.tenant_id == files.c.tenant_id, file_references.c.file_id == files.c.id)
            .scalar_subquery()
            .label("reference_count")
        )

    # ── writes ──

    async def insert_upload(
        self, values: Mapping[str, Any], *, idempotency: Mapping[str, str] | None = None
    ) -> tuple[str, str] | None:
        """Inserts an upload, and with `idempotency` ({key_hash, request_hash}) claims the key for it in the same
        transaction. When another upload already holds the key, nothing is written and (its file id, its request
        hash) is returned."""
        tenant = str(values["tenant_id"])
        try:
            async with self.engine.begin() as c:
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
                await c.execute(sa.insert(files).values(**values))
        except IntegrityError:
            if idempotency is None:
                raise
            held = await self.idempotent_upload(tenant, idempotency["key_hash"])
            if held is None:
                raise
            return held
        return None

    async def idempotent_upload(self, tenant: str, key_hash: str) -> tuple[str, str] | None:
        """(file id, request hash) an Idempotency-Key already holds, or None."""
        async with self.engine.connect() as c:
            row = (
                await c.execute(
                    sa.select(file_idempotency.c.file_id, file_idempotency.c.request_hash).where(
                        file_idempotency.c.tenant_id == tenant, file_idempotency.c.key_hash == key_hash
                    )
                )
            ).first()
        return (str(row[0]), str(row[1])) if row is not None else None

    async def repoint_idempotency(self, tenant: str, from_file: str, to_file: str) -> None:
        """A deduplicated upload's keys now name the file it was folded into, so a retry finds that file."""
        async with self.engine.begin() as c:
            await c.execute(
                sa.update(file_idempotency)
                .where(file_idempotency.c.tenant_id == tenant, file_idempotency.c.file_id == from_file)
                .values(file_id=to_file)
            )

    async def update(self, tenant: str, file_id: str, values: Mapping[str, Any]) -> None:
        async with self.engine.begin() as c:
            await c.execute(sa.update(files).where(files.c.tenant_id == tenant, files.c.id == file_id).values(**values))

    async def make_available(
        self, tenant: str, file_id: str, values: Mapping[str, Any], version: Mapping[str, Any]
    ) -> str | None:
        """Marks an upload available and claims its digest for the team in one transaction. When another file of the
        team already holds the digest, nothing is written and that file's id is returned."""
        row = await self.get(tenant, file_id)
        assert row is not None
        try:
            async with self.engine.begin() as c:
                await c.execute(
                    sa.insert(file_blobs).values(
                        tenant_id=tenant, team=row["team"], digest=values["digest"], file_id=file_id
                    )
                )
                await c.execute(
                    sa.update(files)
                    .where(files.c.tenant_id == tenant, files.c.id == file_id, files.c.status == "uploading")
                    .values(**values)
                )
                await c.execute(sa.insert(file_versions).values(file_id=file_id, tenant_id=tenant, **version))
        except IntegrityError:
            async with self.engine.connect() as c:
                return (
                    await c.execute(
                        sa.select(file_blobs.c.file_id).where(
                            file_blobs.c.tenant_id == tenant,
                            file_blobs.c.team == row["team"],
                            file_blobs.c.digest == values["digest"],
                        )
                    )
                ).scalar_one()
        return None

    async def remove(self, tenant: str, file_id: str, *, event: Mapping[str, Any] | None = None) -> None:
        """Deletes the file's rows; the digest is free again for its team. Hold history stays. `event` (team, actor,
        payload) is written to the outbox in the same transaction, so the deletion and its file.deleted event commit
        together and a relay delivers it however long agents-service is down (c-250)."""
        async with self.engine.begin() as c:
            if event is not None:
                await add_event(
                    c,
                    service_outbox,
                    tenant_id=tenant,
                    team_id=str(event["team"]),
                    name="file.deleted",
                    key=file_id,
                    payload=dict(event["payload"]),
                    actor=event.get("actor"),
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

    async def place_hold(self, tenant: str, file_id: str, hold_id: str, *, by: str, at: datetime, reason: str) -> None:
        async with self.engine.begin() as c:
            await c.execute(
                sa.insert(file_legal_holds).values(
                    id=hold_id, tenant_id=tenant, file_id=file_id, placed_by=by, placed_at=at, reason=reason
                )
            )

    async def release_hold(self, tenant: str, hold_id: str, *, by: str, at: datetime, reason: str) -> None:
        async with self.engine.begin() as c:
            await c.execute(
                sa.update(file_legal_holds)
                .where(file_legal_holds.c.tenant_id == tenant, file_legal_holds.c.id == hold_id)
                .values(released_by=by, released_at=at, release_reason=reason)
            )

    async def add_reference(self, tenant: str, values: Mapping[str, Any]) -> bool:
        """False when the file already has this reference."""
        try:
            async with self.engine.begin() as c:
                await c.execute(sa.insert(file_references).values(tenant_id=tenant, **values))
        except IntegrityError:
            return False
        return True

    async def remove_reference(self, tenant: str, file_id: str, ref_type: str, ref_id: str) -> None:
        async with self.engine.begin() as c:
            await c.execute(
                sa.delete(file_references).where(
                    file_references.c.tenant_id == tenant,
                    file_references.c.file_id == file_id,
                    file_references.c.ref_type == ref_type,
                    file_references.c.ref_id == ref_id,
                )
            )

    async def set_blocked(self, tenant: str, file_id: str, blocked: str | None) -> None:
        async with self.engine.begin() as c:
            await c.execute(
                sa.update(file_references)
                .where(file_references.c.tenant_id == tenant, file_references.c.file_id == file_id)
                .values(blocked=blocked)
            )
