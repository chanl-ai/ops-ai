# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The one place a file is read: every caller (extraction, classify, layouts, a knowledge base, a chat attachment, an
agent's read_file) asks for the file's reading, made once per team, file content digest, reader version and OCR
settings and kept. Bytes come through files-service as the caller's team, so a file the team cannot see has no reading
(FileMissingError), and a reading is never shared with another team, even one holding a file of the same bytes.

A small file with no page to OCR is read at once. Anything else is queued and read in the background, a few at a time
per process, oldest first and one per team while another team waits, each finished page saved as it ends so a restart
carries on from the next page. A reading ends done or failed with a reason, and its end is reported as
`reading.finished` or `reading.failed` for each of the team's files holding those bytes."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ops_documents.errors import FileMissingError, FileNotReadyError
from ops_documents.files import Files, Who
from ops_documents.store.readings import PENDING, ReadingRow, ReadingsStore
from ops_files_client import FileInfo
from ops_ingest.reading import (
    READER_VERSION,
    FileFacts,
    FileReader,
    Page,
    Reading,
    ReadingError,
    ReadingSettings,
    open_file,
    read,
)
from ops_service_kit.logging import get_logger
from ops_store import isolation

log = get_logger("ops_documents.readings")

# A file up to this size and page count, with no page to OCR, is read inside the request that asks for it.
SYNC_PAGES = 5
SYNC_BYTES = 5 * 1024 * 1024
# Files read at once in one process.
SLOTS = 2
# A page that takes longer is listed as unread with the reason, and the read goes on with the next page.
PAGE_TIMEOUT_S = 60.0
# A reading that failed for an unexpected reason this many times is given up, with the reason.
MAX_TRIES = 3
TOO_MANY_TRIES = f"stopped after {MAX_TRIES} tries"


def settings_of(ocr: str | bool | None, language: str | None = None) -> ReadingSettings:
    """A request's OCR choice as reading settings: `true` and `false` from older callers mean `auto` and `off`."""
    mode = "auto" if ocr is True else "off" if ocr is False else (ocr or "auto")
    return ReadingSettings.model_validate({"ocr": mode, "language": language or "eng"})


def next_reading(queued: Sequence[ReadingRow], running_teams: Sequence[str]) -> int | None:
    """Which queued reading starts next: the oldest whose team has nothing running while another team waits, so one
    team's bulk upload does not hold up the rest; the oldest of all when every waiting team is already reading."""
    if not queued:
        return None
    busy = set(running_teams)
    for i, row in enumerate(queued):
        if row.team not in busy:
            return i
    return 0


def answer_of(row: ReadingRow, file_id: str, pages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """What a caller reads: the reading's status and progress, then, once done, the file's facts and its pages."""
    mode, _, language = row.key.partition(":")
    out: dict[str, Any] = {
        "fileId": file_id,
        "digest": row.digest,
        "status": row.status,
        "readerVersion": row.version,
        "settings": {"ocr": mode, "language": language},
        "pagesTotal": row.pages_total,
        "pagesDone": row.pages_done,
    }
    if row.status == "failed":
        out["error"] = {"code": row.error_code or "failed", "message": row.error or ""}
    if row.status == "done":
        out["facts"] = row.facts
        out["durationMs"] = row.duration_ms
        if pages is not None:
            out["pages"] = pages
    return out


def _identity(row: ReadingRow) -> tuple[str, ...]:
    return (row.tenant_id, row.team, row.digest, row.version, row.key)


def _read_now(data: bytes, file: FileInfo, settings: ReadingSettings) -> Reading | None:
    """The whole reading when the file is small enough and needs no OCR, else None (it is queued instead)."""
    with open_file(data, filename=file.name, mime_type=file.mime, settings=settings) as reader:
        count = reader.facts.page_count
        if count > SYNC_PAGES or any(reader.needs_ocr(n) for n in range(1, count + 1)):
            return None
        started = time.perf_counter()
        pages = [reader.page(n) for n in range(1, count + 1)]
        took = round((time.perf_counter() - started) * 1000)
        return Reading(settings=settings, facts=reader.facts, pages=pages, duration_ms=took)


@dataclass
class Readings:
    files: Files
    store: ReadingsStore
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    slots: int = SLOTS
    page_timeout_s: float = PAGE_TIMEOUT_S
    _queued: list[ReadingRow] = field(default_factory=list[ReadingRow])
    _running: dict[tuple[str, ...], str] = field(default_factory=dict[tuple[str, ...], str])
    _tasks: set[asyncio.Task[None]] = field(default_factory=set[asyncio.Task[None]])

    # ── Asking ────────────────────────────────────────────────────────────

    async def ask(self, who: Who, file_id: str, settings: ReadingSettings) -> tuple[int, dict[str, Any]]:
        """(200, the reading) when it is stored or was made now, (202, its status) when it is read in the background,
        (200, failed with the reason) for a file that cannot be read at all."""
        file = await self.files.readable(who, file_id)
        digest = self._digest(file)
        await self.store.link(file.id, who.team, digest, self.clock())
        row = await self.store.get(who.team, digest, READER_VERSION, settings.key)
        if row is not None and row.status == "done":
            return 200, answer_of(row, file_id, await self.store.pages(who.team, digest, READER_VERSION, settings.key))
        if row is not None and row.status in PENDING:
            return 202, answer_of(row, file_id)
        if file.size <= SYNC_BYTES:
            data = await self.files.read(who, file)
            try:
                made = await asyncio.to_thread(_read_now, data, file, settings)
            except ReadingError as e:
                failed = await self._failed_now(who, file, settings, e)
                return 200, answer_of(failed, file_id)
            if made is not None:
                await self._keep(who, file, made)
                row = await self.store.get(who.team, digest, READER_VERSION, settings.key)
                assert row is not None
                return 200, answer_of(row, file_id, [p.model_dump(mode="json", by_alias=True) for p in made.pages])
        row = await self.store.queue(
            digest, READER_VERSION, settings.key, file_id=file.id, team=who.team, actor=who.actor, at=self.clock()
        )
        if row.status in PENDING:
            self._later(row)
        return 202, answer_of(row, file_id)

    async def get(
        self, who: Who, file_id: str, settings: ReadingSettings, *, page: int | None = None
    ) -> dict[str, Any]:
        """The reading as it is now, with its pages (or one page) once done; status `none` when never asked for."""
        file = await self.files.readable(who, file_id)
        digest = self._digest(file)
        row = await self.store.get(who.team, digest, READER_VERSION, settings.key)
        if row is None:
            mode, language = settings.ocr, settings.language
            return {"fileId": file_id, "digest": digest, "status": "none", "readerVersion": READER_VERSION,
                    "settings": {"ocr": mode, "language": language}, "pagesTotal": None, "pagesDone": 0}  # fmt: skip
        pages = (
            await self.store.pages(who.team, digest, READER_VERSION, settings.key, page=page)
            if row.status == "done"
            else None
        )
        return answer_of(row, file_id, pages)

    async def of(self, who: Who, file: FileInfo, settings: ReadingSettings) -> Reading:
        """The file's reading for a caller inside this service (an extraction already running in the background): the
        stored one, or read now and kept."""
        digest = self._digest(file)
        await self.store.link(file.id, who.team, digest, self.clock())
        stored = await self.stored_of(who.team, digest, settings)
        if stored is not None:
            return stored
        data = await self.files.read(who, file)
        made = await asyncio.to_thread(read, data, filename=file.name, mime_type=file.mime, settings=settings)
        await self._keep(who, file, made)
        return made

    async def stored_of(self, team: str, digest: str, settings: ReadingSettings) -> Reading | None:
        """The team's finished reading of these bytes under these settings, without reading anything."""
        row = await self.store.get(team, digest, READER_VERSION, settings.key)
        if row is None or row.status != "done" or row.facts is None:
            return None
        pages = await self.store.pages(team, digest, READER_VERSION, settings.key)
        return Reading(
            settings=settings,
            facts=FileFacts.model_validate(row.facts),
            pages=[Page.model_validate(p) for p in pages],
            duration_ms=row.duration_ms or 0,
        )

    async def stored(self, who: Who, file_id: str, settings: ReadingSettings) -> Reading | None:
        return await self.stored_of(who.team, self._digest(await self.files.readable(who, file_id)), settings)

    async def purge(self, who: Who, file_id: str) -> int:
        return await self.store.purge(file_id, who.team)

    @staticmethod
    def _digest(file: FileInfo) -> str:
        if not file.digest:
            raise FileNotReadyError(f"{file.id} has no content digest yet")
        return file.digest

    async def _keep(self, who: Who, file: FileInfo, made: Reading) -> None:
        await self.store.put_done(
            self._digest(file),
            READER_VERSION,
            made.settings.key,
            facts=made.facts.model_dump(mode="json", by_alias=True),
            pages=[p.model_dump(mode="json", by_alias=True) for p in made.pages],
            file_id=file.id,
            team=who.team,
            actor=who.actor,
            duration_ms=made.duration_ms,
            at=self.clock(),
        )

    async def _failed_now(self, who: Who, file: FileInfo, settings: ReadingSettings, e: ReadingError) -> ReadingRow:
        digest = self._digest(file)
        row = await self.store.queue(
            digest, READER_VERSION, settings.key, file_id=file.id, team=who.team, actor=who.actor, at=self.clock()
        )
        await self.store.start(row, at=self.clock())
        await self.store.finish(row, status="failed", at=self.clock(), error_code=e.code, error=str(e))
        found = await self.store.get(who.team, digest, READER_VERSION, settings.key)
        assert found is not None
        return found

    # ── The queue ─────────────────────────────────────────────────────────

    async def resume(self) -> int:
        """Queues every unfinished reading again after a restart; the number queued."""
        pending = await self.store.pending()
        for row in pending:
            self._later(row)
        return len(pending)

    async def drain(self) -> None:
        """Waits for every queued and running reading in this process (tests and shutdown)."""
        while self._tasks or self._queued:
            if self._tasks:
                await asyncio.gather(*list(self._tasks), return_exceptions=True)
            else:
                self._pump()

    def _later(self, row: ReadingRow) -> None:
        key = _identity(row)
        if key in self._running or any(_identity(q) == key for q in self._queued):
            return
        self._queued.append(row)
        self._pump()

    def _pump(self) -> None:
        while len(self._running) < self.slots:
            i = next_reading(self._queued, list(self._running.values()))
            if i is None:
                return
            row = self._queued.pop(i)
            key = _identity(row)
            self._running[key] = row.team
            task = asyncio.create_task(self._background(row))
            self._tasks.add(task)

            def done(t: asyncio.Task[None], key: tuple[str, ...] = key) -> None:
                self._tasks.discard(t)
                self._running.pop(key, None)
                self._pump()

            task.add_done_callback(done)

    async def _background(self, row: ReadingRow) -> None:
        with isolation.scope(row.tenant_id, row.team):
            try:
                await self._run(row)
            except Exception as e:
                log.warning("reading failed", extra={"digest": row.digest, "error": str(e)})

    async def _run(self, row: ReadingRow) -> None:
        tries = await self.store.start(row, at=self.clock())
        if tries > MAX_TRIES:
            await self.store.finish(
                row, status="failed", at=self.clock(), error_code="too_many_tries", error=TOO_MANY_TRIES
            )
            return
        who = Who(tenant_id=row.tenant_id, team=row.team, actor=row.actor)
        try:
            file = await self.files.readable(who, row.file_id)
            data = await self.files.read(who, file)
        except (FileMissingError, FileNotReadyError) as e:
            await self.store.finish(row, status="failed", at=self.clock(), error_code="file_unavailable", error=str(e))
            return
        settings = settings_of(*row.key.split(":", 1))
        started = time.perf_counter()
        stack = ExitStack()
        try:
            reader = await asyncio.to_thread(self._open, stack, data, file, settings)
            total = reader.facts.page_count
            await self.store.opened(row, pages_total=total, facts=reader.facts.model_dump(mode="json", by_alias=True))
            for number in range(row.pages_done + 1, total + 1):
                try:
                    page = await asyncio.wait_for(asyncio.to_thread(reader.page, number), self.page_timeout_s)
                except TimeoutError:
                    page = Page(
                        number=number,
                        source="none",
                        unread_reason=f"reading the page took over {round(self.page_timeout_s)} seconds",
                    )
                    # The page's thread may still be running on the open file, so the rest is read from a fresh one.
                    stack.close()
                    stack = ExitStack()
                    reader = await asyncio.to_thread(self._open, stack, data, file, settings)
                await self.store.save_page(row, number, page.model_dump(mode="json", by_alias=True))
            took = round((time.perf_counter() - started) * 1000)
            done = await self.store.get(row.team, row.digest, row.version, row.key)
            await self.store.finish(done or row, status="done", at=self.clock(), duration_ms=took)
        except ReadingError as e:
            await self.store.finish(row, status="failed", at=self.clock(), error_code=e.code, error=str(e))
        except Exception as e:
            if tries >= MAX_TRIES:
                await self.store.finish(
                    row, status="failed", at=self.clock(), error_code="too_many_tries", error=f"{TOO_MANY_TRIES}: {e}"
                )
            else:
                again = await self.store.get(row.team, row.digest, row.version, row.key)
                if again is not None:
                    self._queued.append(again)
            raise
        finally:
            stack.close()

    @staticmethod
    def _open(stack: ExitStack, data: bytes, file: FileInfo, settings: ReadingSettings) -> FileReader:
        return stack.enter_context(open_file(data, filename=file.name, mime_type=file.mime, settings=settings))
