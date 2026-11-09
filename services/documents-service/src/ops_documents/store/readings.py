# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Readings at rest: one per tenant, file content digest (files-service's), reader version and settings key, so the
same bytes are read once for every caller and purpose, and a change to the reader or the OCR settings reads them again.

A reading's pages are saved one row at a time as gzipped JSON, so a long read that stops carries on from its next
page. Which files point at a reading is kept beside it, for the events a finished reading sends each team that asked
and for removing a reading once no file of the tenant holds those bytes. JSON is kept as text or bytes and never
queried (database portability D5)."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_documents.store.extractions import service_outbox
from ops_documents.store.metadata import RECOVER_PENDING, ROLE, SYSTEM_ROLE, metadata
from ops_store import isolation
from ops_store.outbox import add
from ops_store.schema import TENANT_SCOPED

ReadingStatus = Literal["queued", "reading", "done", "failed"]
PENDING: tuple[ReadingStatus, ...] = ("queued", "reading")
FINISHED_EVENT = "reading.finished"
FAILED_EVENT = "reading.failed"

_KEY = (
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("file_digest", sa.String(64), primary_key=True),
    sa.Column("reader_version", sa.String(32), primary_key=True),
    # The OCR mode and language (ops_ingest.reading.ReadingSettings.key), e.g. "auto:eng".
    sa.Column("settings_key", sa.String(64), primary_key=True),
)

documents_readings = sa.Table(
    "documents_readings",
    metadata,
    *(c.copy() for c in _KEY),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("pages_total", sa.Integer),
    sa.Column("pages_done", sa.Integer, nullable=False),
    # ops_ingest.reading.FileFacts as JSON: page count, title, author, dates, warnings.
    sa.Column("facts", sa.Text),
    sa.Column("error_code", sa.String(64)),
    sa.Column("error", sa.Text),
    sa.Column("attempts", sa.Integer, nullable=False),
    # Whom a queued read reads the bytes as after a restart: a file the team that asked can see.
    sa.Column("file_id", sa.String(64), nullable=False),
    sa.Column("team", sa.String(64), nullable=False),
    sa.Column("actor", sa.String(320), nullable=False),
    sa.Column("duration_ms", sa.Integer),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Index("ix_documents_readings_status", "status"),
    # Workspace-level, like the bytes: any team holding a file with these bytes may be given its reading.
    info=TENANT_SCOPED,
)

documents_reading_pages = sa.Table(
    "documents_reading_pages",
    metadata,
    *(c.copy() for c in _KEY),
    sa.Column("page", sa.Integer, primary_key=True),
    # ops_ingest.reading.Page as gzipped JSON: about five times smaller than the text.
    sa.Column("body", sa.LargeBinary, nullable=False),
    info=TENANT_SCOPED,
)

documents_reading_files = sa.Table(
    "documents_reading_files",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("file_id", sa.String(64), primary_key=True),
    sa.Column("team", sa.String(64), primary_key=True),
    sa.Column("file_digest", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_documents_reading_files_digest", "tenant_id", "file_digest"),
    info=TENANT_SCOPED,
)


@dataclass(frozen=True)
class ReadingRow:
    tenant_id: str
    digest: str
    version: str
    key: str
    status: ReadingStatus
    pages_total: int | None
    pages_done: int
    facts: dict[str, Any] | None
    error_code: str | None
    error: str | None
    attempts: int
    file_id: str
    team: str
    actor: str
    duration_ms: int | None


def _row(m: Any) -> ReadingRow:
    return ReadingRow(
        tenant_id=m["tenant_id"],
        digest=m["file_digest"],
        version=m["reader_version"],
        key=m["settings_key"],
        status=m["status"],
        pages_total=m["pages_total"],
        pages_done=m["pages_done"],
        facts=json.loads(m["facts"]) if m["facts"] else None,
        error_code=m["error_code"],
        error=m["error"],
        attempts=m["attempts"],
        file_id=m["file_id"],
        team=m["team"],
        actor=m["actor"],
        duration_ms=m["duration_ms"],
    )


def _pack(page: dict[str, Any]) -> bytes:
    return gzip.compress(json.dumps(page, separators=(",", ":")).encode())


def _unpack(body: bytes) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(gzip.decompress(body))
    return out


class ReadingsStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    @staticmethod
    def _where(t: sa.Table, digest: str, version: str, key: str) -> sa.ColumnElement[bool]:
        return sa.and_(
            t.c.tenant_id == isolation.tenant(),
            t.c.file_digest == digest,
            t.c.reader_version == version,
            t.c.settings_key == key,
        )

    async def get(self, digest: str, version: str, key: str) -> ReadingRow | None:
        t = documents_readings
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            m = (await c.execute(sa.select(t).where(self._where(t, digest, version, key)))).mappings().first()
        return _row(m) if m is not None else None

    async def link(self, file_id: str, team: str, digest: str, at: datetime) -> None:
        """Records that the team's file holds these bytes; a file that changes content is linked to its new digest."""
        t = documents_reading_files
        tenant = isolation.tenant()
        mine = sa.and_(t.c.tenant_id == tenant, t.c.file_id == file_id, t.c.team == team)
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            now = (await c.execute(sa.select(t.c.file_digest).where(mine))).scalar_one_or_none()
            if now is not None:
                if now != digest:
                    await c.execute(sa.update(t).where(mine).values(file_digest=digest, created_at=at))
                return
        try:
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                await c.execute(
                    sa.insert(t).values(tenant_id=tenant, file_id=file_id, team=team, file_digest=digest, created_at=at)
                )
        except IntegrityError:
            return  # linked by a request racing this one

    async def queue(
        self, digest: str, version: str, key: str, *, file_id: str, team: str, actor: str, at: datetime
    ) -> ReadingRow:
        """The reading queued, or the one already there; a failed reading asked for again is queued afresh."""
        t = documents_readings
        values = {
            "tenant_id": isolation.tenant(),
            "file_digest": digest,
            "reader_version": version,
            "settings_key": key,
            "status": "queued",
            "pages_done": 0,
            "attempts": 0,
            "file_id": file_id,
            "team": team,
            "actor": actor,
            "created_at": at,
        }
        try:
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                await c.execute(sa.insert(t).values(**values))
        except IntegrityError:
            found = await self.get(digest, version, key)
            assert found is not None
            if found.status != "failed":
                return found
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                await c.execute(
                    sa.delete(documents_reading_pages).where(self._where(documents_reading_pages, digest, version, key))
                )
                await c.execute(
                    sa.update(t)
                    .where(self._where(t, digest, version, key), t.c.status == "failed")
                    .values(
                        status="queued", pages_done=0, pages_total=None, attempts=0, error_code=None, error=None,
                        file_id=file_id, team=team, actor=actor, created_at=at, started_at=None, finished_at=None,
                    )
                )  # fmt: skip
        found = await self.get(digest, version, key)
        assert found is not None
        return found

    async def start(self, row: ReadingRow, *, at: datetime) -> int:
        """Marks the reading begun once more; the number of tries, this one included."""
        t = documents_readings
        tries = row.attempts + 1
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await c.execute(
                sa.update(t)
                .where(self._where(t, row.digest, row.version, row.key))
                .values(status="reading", attempts=tries, started_at=at)
            )
        return tries

    async def opened(self, row: ReadingRow, *, pages_total: int, facts: dict[str, Any]) -> None:
        t = documents_readings
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await c.execute(
                sa.update(t)
                .where(self._where(t, row.digest, row.version, row.key))
                .values(pages_total=pages_total, facts=json.dumps(facts))
            )

    async def save_page(self, row: ReadingRow, number: int, page: dict[str, Any]) -> None:
        """One finished page, and the count of pages done; saving a page again (after a restart) replaces it."""
        t = documents_readings
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await self._put_page(c, row.digest, row.version, row.key, number=number, page=page)
            await c.execute(
                sa.update(t).where(self._where(t, row.digest, row.version, row.key)).values(pages_done=number)
            )

    async def _put_page(
        self, c: AsyncConnection, digest: str, version: str, key: str, *, number: int, page: dict[str, Any]
    ) -> None:
        p = documents_reading_pages
        await c.execute(sa.delete(p).where(self._where(p, digest, version, key), p.c.page == number))
        await c.execute(
            sa.insert(p).values(
                tenant_id=isolation.tenant(),
                file_digest=digest,
                reader_version=version,
                settings_key=key,
                page=number,
                body=_pack(page),
            )
        )

    async def put_done(
        self,
        digest: str,
        version: str,
        key: str,
        *,
        facts: dict[str, Any],
        pages: list[dict[str, Any]],
        file_id: str,
        team: str,
        actor: str,
        duration_ms: int,
        at: datetime,
    ) -> None:
        """A reading made at once, kept whole in one transaction; two readers of the same bytes racing keep one."""
        t = documents_readings
        try:
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                await c.execute(sa.delete(t).where(self._where(t, digest, version, key)))
                await c.execute(
                    sa.delete(documents_reading_pages).where(self._where(documents_reading_pages, digest, version, key))
                )
                await c.execute(
                    sa.insert(t).values(
                        tenant_id=isolation.tenant(), file_digest=digest, reader_version=version, settings_key=key,
                        status="done", pages_total=len(pages), pages_done=len(pages), facts=json.dumps(facts),
                        attempts=1, file_id=file_id, team=team, actor=actor, duration_ms=duration_ms,
                        created_at=at, started_at=at, finished_at=at,
                    )
                )  # fmt: skip
                for page in pages:
                    await self._put_page(c, digest, version, key, number=int(page["number"]), page=page)
                await self._events(
                    c, digest, version, key, name=FINISHED_EVENT, said={"status": "done", "pages": len(pages)}
                )
        except IntegrityError:
            return

    async def finish(
        self,
        row: ReadingRow,
        *,
        status: Literal["done", "failed"],
        at: datetime,
        duration_ms: int | None = None,
        error_code: str | None = None,
        error: str | None = None,
    ) -> None:
        """The reading ended, and the event each team with a file of these bytes is sent, in one transaction."""
        t = documents_readings
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await c.execute(
                sa.update(t)
                .where(self._where(t, row.digest, row.version, row.key))
                .values(status=status, finished_at=at, duration_ms=duration_ms, error_code=error_code, error=error)
            )
            name = FINISHED_EVENT if status == "done" else FAILED_EVENT
            said: dict[str, Any] = {"status": status, "pages": row.pages_total}
            if error_code:
                said |= {"errorCode": error_code, "error": error}
            await self._events(c, row.digest, row.version, row.key, name=name, said=said)

    async def _events(
        self, c: AsyncConnection, digest: str, version: str, key: str, *, name: str, said: dict[str, Any]
    ) -> None:
        f = documents_reading_files
        tenant = isolation.tenant()
        held = (
            await c.execute(sa.select(f.c.file_id, f.c.team).where(f.c.tenant_id == tenant, f.c.file_digest == digest))
        ).all()
        for file_id, team in held:
            payload = {"fileId": file_id, "digest": digest, "readerVersion": version, "settingsKey": key, **said}
            await add(
                c, service_outbox, tenant_id=tenant, team_id=team, name=name,
                key=f"{name}:{digest}:{version}:{key}:{file_id}", payload=payload,
            )  # fmt: skip

    async def pages(self, digest: str, version: str, key: str, *, page: int | None = None) -> list[dict[str, Any]]:
        p = documents_reading_pages
        query = sa.select(p.c.body).where(self._where(p, digest, version, key)).order_by(p.c.page)
        if page is not None:
            query = query.where(p.c.page == page)
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            bodies = (await c.execute(query)).scalars().all()
        return [_unpack(b) for b in bodies]

    async def pending(self) -> list[ReadingRow]:
        """Every queued or unfinished reading, across tenants, oldest first: what a restart picks up again."""
        t = documents_readings
        async with isolation.system_tx(self.engine, RECOVER_PENDING, role=SYSTEM_ROLE) as c:
            rows = (
                (await c.execute(sa.select(t).where(t.c.status.in_(PENDING)).order_by(t.c.created_at))).mappings().all()
            )
        return [_row(m) for m in rows]

    async def purge(self, file_id: str, team: str) -> int:
        """Forgets that the team's deleted file held its bytes, and removes the readings of those bytes once no other
        file of the tenant holds them; the number of readings removed."""
        f, t, p = documents_reading_files, documents_readings, documents_reading_pages
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            mine = sa.and_(f.c.tenant_id == tenant, f.c.file_id == file_id, f.c.team == team)
            digest = (await c.execute(sa.select(f.c.file_digest).where(mine))).scalar_one_or_none()
            if digest is None:
                return 0
            await c.execute(sa.delete(f).where(mine))
            others = sa.select(sa.func.count()).where(f.c.tenant_id == tenant, f.c.file_digest == digest)
            if (await c.execute(others)).scalar_one():
                return 0
            await c.execute(sa.delete(p).where(p.c.tenant_id == tenant, p.c.file_digest == digest))
            removed = await c.execute(sa.delete(t).where(t.c.tenant_id == tenant, t.c.file_digest == digest))
        return int(removed.rowcount or 0)
