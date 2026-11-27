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
from datetime import UTC, datetime, timedelta

from ops_documents.errors import FileMissingError, FileNotReadyError, PolicyUnreadError
from ops_documents.files import Files, Who
from ops_documents.pending import Pending
from ops_documents.picture_reading import (
    PICTURE_RETRIES,
    PictureReading,
    as_read,
    not_described,
    stricter,
    wants_picture,
)
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
from ops_service_kit.http import Json
from ops_service_kit.logging import get_logger
from ops_store import background, isolation

log = get_logger("ops_documents.readings")

# A file up to this size and page count, with no page to OCR, is read inside the request that asks for it.
SYNC_PAGES = 5
SYNC_BYTES = 5 * 1024 * 1024
# Files read at once in one process.
SLOTS = 2
# The process every background reading, extraction and type test reports under on /health/background.
READING_PROCESS = "document_reading"
# A page that takes longer is listed as unread with the reason, and the read goes on with the next page.
PAGE_TIMEOUT_S = 60.0
# A reading that failed for an unexpected reason this many times is given up, with the reason.
MAX_TRIES = 3
TOO_MANY_TRIES = f"stopped after {MAX_TRIES} tries"


def settings_of(ocr: str | bool | None, language: str | None = None) -> ReadingSettings:
    """A request's OCR choice as reading settings: `true` and `false` from older callers mean `auto` and `off`."""
    mode = "auto" if ocr is True else "off" if ocr is False else (ocr or "auto")
    return ReadingSettings.model_validate({"ocr": mode, "language": language or "eng"})


# A knowledge read asks for page pictures with the source's sensitivity, raised to the file's own level. The answer is
# part of the reading's key, so a reading made while the team's policy was off, or for another sensitivity, is not
# served once that changes.
PICTURES_OFF = "p-off"
# Kept on a finished reading with a page whose picture was refused for a reason that passes (the model busy, today's
# limit). The reading is served as it is; an ask once RETRY_AFTER has passed describes those pages again in the
# background, alone, keeping every other page.
RETRY_PICTURES = "pictures_retry"
RETRY_AFTER = timedelta(minutes=10)
POLICY_UNREAD = "The team's page picture policy could not be read. Try again shortly."


def reading_key(settings: ReadingSettings, pictures: str | None, allowed: bool) -> str:
    """The stored reading's key: the OCR settings, then whether pictures were asked for, allowed, and at what
    sensitivity."""
    if pictures is None:
        return settings.key
    return f"{settings.key}:{f'p-{pictures}' if allowed else PICTURES_OFF}"


def key_parts(key: str) -> tuple[ReadingSettings, bool, str | None]:
    """A stored key as (settings, pictures asked for, the sensitivity they may be sent at, None when not allowed)."""
    ocr, language, *rest = key.split(":")
    if not rest:
        return settings_of(ocr, language), False, None
    return settings_of(ocr, language), True, None if rest[0] == PICTURES_OFF else rest[0].removeprefix("p-")


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


def answer_of(row: ReadingRow, file_id: str, pages: Sequence[Page] | None = None) -> Json:
    """What a caller reads: the reading's status and progress, then, once done, the file's facts and its pages."""
    settings = key_parts(row.key)[0]
    out: Json = {
        "fileId": file_id,
        "digest": row.digest,
        "status": row.status,
        "readerVersion": row.version,
        "settings": {"ocr": settings.ocr, "language": settings.language},
        "pagesTotal": row.pages_total,
        "pagesDone": row.pages_done,
    }
    if row.status == "failed":
        out["error"] = {"code": row.error_code or "failed", "message": row.error or ""}
    if row.status == "done":
        out["facts"] = row.facts
        out["durationMs"] = row.duration_ms
        if pages is not None:
            out["pages"] = [p.model_dump(mode="json", by_alias=True) for p in pages]
    return out


def _identity(row: ReadingRow) -> tuple[str, ...]:
    return (row.tenant_id, row.team, row.digest, row.version, row.key)


def _read_now(data: bytes, file: FileInfo, settings: ReadingSettings, *, pictures: bool = False) -> Reading | None:
    """The whole reading when the file is small enough and needs no OCR, else None (it is queued instead). With
    picture reading on, a file with a page a model could describe is queued too, since a model call does not belong
    inside the request."""
    with open_file(data, filename=file.name, mime_type=file.mime, settings=settings) as reader:
        count = reader.facts.page_count
        if count > SYNC_PAGES or any(reader.needs_ocr(n) for n in range(1, count + 1)):
            return None
        started = time.perf_counter()
        pages = [reader.page(n) for n in range(1, count + 1)]
        if pictures and any(wants_picture(p, reader.facts.mime_type) for p in pages):
            return None
        took = round((time.perf_counter() - started) * 1000)
        return Reading(settings=settings, facts=reader.facts, pages=pages, duration_ms=took)


@dataclass
class Readings:
    files: Files
    store: ReadingsStore
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    slots: int = SLOTS
    page_timeout_s: float = PAGE_TIMEOUT_S
    # Describes pages that came out with no text; None reads text and OCR only.
    pictures: PictureReading | None = None
    _queued: list[ReadingRow] = field(default_factory=list[ReadingRow])
    _running: dict[tuple[str, ...], str] = field(default_factory=dict[tuple[str, ...], str])
    _pending: Pending = field(default_factory=Pending)

    # ── Asking ────────────────────────────────────────────────────────────

    async def ask(
        self, who: Who, file_id: str, settings: ReadingSettings, *, pictures: str | None = None
    ) -> tuple[int, Json]:
        """(200, the reading) when it is stored or was made now, (202, its status) when it is read in the background,
        (200, failed with the reason) for a file that cannot be read at all. `pictures` is the sensitivity a knowledge
        read may send page pictures at; None reads text and OCR only."""
        file = await self.files.readable(who, file_id)
        digest = self._digest(file)
        level = None if pictures is None else stricter(file.sensitivity, pictures)
        key, kept = await self._key_kept(who, settings, level)
        # A stored reading is found on the kept policy; one about to be made asks the policy again (`fresh`).
        for fresh in (False, True):
            if key is None:
                return 200, await self._without_policy(who, file, settings, level)
            # Gate: the file's link and its stored reading in one transaction, closed before the bytes are read.
            async with isolation.request_transaction():
                await self.store.link(file.id, who.team, digest, self.clock())
                row = await self.store.get(who.team, digest, READER_VERSION, key)
                done = row is not None and row.status == "done"
                pages = await self.store.pages(who.team, digest, READER_VERSION, key) if done else None
            if row is not None and pages is not None:
                await self._retry_if_due(who, file, row)
                return 200, answer_of(row, file_id, pages)
            if row is not None and row.status in PENDING:
                return 202, answer_of(row, file_id)
            live = key if fresh or not kept else await self._key(who, settings, level, fresh=True)
            if live == key:
                break
            key = live
        if key is None:
            return 200, await self._without_policy(who, file, settings, level)
        if file.size <= SYNC_BYTES:
            data = await self.files.read(who, file)
            try:
                made = await asyncio.to_thread(_read_now, data, file, settings, pictures=key != settings.key)
            except ReadingError as e:
                async with isolation.request_transaction():
                    failed = await self._failed_now(who, file, key, e)
                return 200, answer_of(failed, file_id)
            if made is not None:
                async with isolation.request_transaction():
                    await self._keep(who, file, made, key)
                    row = await self.store.get(who.team, digest, READER_VERSION, key)
                assert row is not None
                return 200, answer_of(row, file_id, made.pages)
        # The queued row commits before the task that reads it starts, so the task finds it.
        async with isolation.request_transaction():
            row = await self.store.queue(
                digest, READER_VERSION, key, file_id=file.id, team=who.team, actor=who.actor, at=self.clock()
            )
        if row.status in PENDING:
            await self._later(row)
        return 202, answer_of(row, file_id)

    async def get(
        self, who: Who, file_id: str, settings: ReadingSettings, *, page: int | None = None, pictures: str | None = None
    ) -> Json:
        """The reading as it is now, with its pages (or one page) once done; status `none` when never asked for."""
        file = await self.files.readable(who, file_id)
        digest = self._digest(file)
        level = None if pictures is None else stricter(file.sensitivity, pictures)
        key = await self._key(who, settings, level)
        if key is None:
            return await self._without_policy(who, file, settings, level, page=page)
        row = await self.store.get(who.team, digest, READER_VERSION, key)
        if row is not None and row.status == "done":
            await self._retry_if_due(who, file, row)
        if row is None:
            mode, language = settings.ocr, settings.language
            return {"fileId": file_id, "digest": digest, "status": "none", "readerVersion": READER_VERSION,
                    "settings": {"ocr": mode, "language": language}, "pagesTotal": None, "pagesDone": 0}  # fmt: skip
        pages = (
            await self.store.pages(who.team, digest, READER_VERSION, key, page=page) if row.status == "done" else None
        )
        return answer_of(row, file_id, pages)

    async def of(self, who: Who, file: FileInfo, settings: ReadingSettings) -> Reading:
        """The file's reading for a caller inside this service (an extraction already running in the background): the
        stored one, or read now and kept."""
        digest = self._digest(file)
        # Gate and settle: the stored reading in one transaction, the bytes read with none open, then the reading kept.
        async with isolation.request_transaction():
            await self.store.link(file.id, who.team, digest, self.clock())
            stored = await self.stored_of(who.team, digest, settings)
        if stored is not None:
            return stored
        data = await self.files.read(who, file)
        made = await asyncio.to_thread(read, data, filename=file.name, mime_type=file.mime, settings=settings)
        async with isolation.request_transaction():
            await self._keep(who, file, made)
        return made

    async def stored_of(self, team: str, digest: str, settings: ReadingSettings) -> Reading | None:
        """The team's finished reading of these bytes under these settings, without reading anything."""
        async with isolation.request_transaction():
            row = await self.store.get(team, digest, READER_VERSION, settings.key)
            if row is None or row.status != "done" or row.facts is None:
                return None
            pages = await self.store.pages(team, digest, READER_VERSION, settings.key)
        return Reading(
            settings=settings,
            facts=FileFacts.model_validate(row.facts),
            pages=pages,
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

    async def _key(self, who: Who, settings: ReadingSettings, level: str | None, *, fresh: bool = False) -> str | None:
        """The reading's key; None when pictures were asked for and the team's policy cannot be read."""
        return (await self._key_kept(who, settings, level, fresh=fresh))[0]

    async def _key_kept(
        self, who: Who, settings: ReadingSettings, level: str | None, *, fresh: bool = False
    ) -> tuple[str | None, bool]:
        """`_key`, and whether it rests on the policy as kept rather than read now."""
        if level is None or self.pictures is None:
            return settings.key, False
        allowed, kept = await self.pictures.answer(who.tenant_id, who.team, fresh=fresh)
        return (None if allowed is None else reading_key(settings, level, allowed)), kept

    async def _without_policy(
        self, who: Who, file: FileInfo, settings: ReadingSettings, level: str | None, *, page: int | None = None
    ) -> Json:
        """With the team's policy unread, the reading already made with pictures or without them; nothing is read or
        kept, so an outage of platform-service never makes a second reading."""
        digest = self._digest(file)
        for allowed in (True, False):
            key = reading_key(settings, level, allowed)
            async with isolation.request_transaction():
                row = await self.store.get(who.team, digest, READER_VERSION, key)
                if row is not None and row.status == "done":
                    pages = await self.store.pages(who.team, digest, READER_VERSION, key, page=page)
                    return answer_of(row, file.id, pages)
        raise PolicyUnreadError(POLICY_UNREAD)

    async def _retry_if_due(self, who: Who, file: FileInfo, row: ReadingRow) -> None:
        """Describes the reading's refused pages again in the background once its wait is over; one process takes it.
        The pages are read from the asker's file, so a first file deleted since does not stop it."""
        if row.error_code != RETRY_PICTURES or self.pictures is None:
            return
        now = self.clock()
        async with isolation.request_transaction():
            claimed = await self.store.claim_retry(row, code=RETRY_PICTURES, at=now, due_before=now - RETRY_AFTER)
        if claimed:
            await self._later(row.model_copy(update={"file_id": file.id, "actor": who.actor}))

    async def _keep(self, who: Who, file: FileInfo, made: Reading, key: str | None = None) -> None:
        await self.store.put_done(
            self._digest(file),
            READER_VERSION,
            key or made.settings.key,
            facts=made.facts.model_dump(mode="json", by_alias=True),
            pages=[p.model_dump(mode="json", by_alias=True) for p in made.pages],
            file_id=file.id,
            team=who.team,
            actor=who.actor,
            duration_ms=made.duration_ms,
            at=self.clock(),
        )

    async def _failed_now(self, who: Who, file: FileInfo, key: str, e: ReadingError) -> ReadingRow:
        digest = self._digest(file)
        row = await self.store.queue(
            digest, READER_VERSION, key, file_id=file.id, team=who.team, actor=who.actor, at=self.clock()
        )
        await self.store.start(row, at=self.clock())
        await self.store.finish(row, status="failed", at=self.clock(), error_code=e.code, error=str(e))
        found = await self.store.get(who.team, digest, READER_VERSION, key)
        assert found is not None
        return found

    # ── The queue ─────────────────────────────────────────────────────────

    async def resume(self) -> int:
        """Queues every unfinished reading again after a restart; the number queued."""
        pending = await self.store.pending()
        for row in pending:
            await self._later(row)
        return len(pending)

    async def drain(self) -> None:
        """Waits until no reading is queued or running in this process (tests and shutdown)."""
        await self._pending.none()

    async def _later(self, row: ReadingRow) -> None:
        key = _identity(row)
        if key in self._running or any(_identity(q) == key for q in self._queued):
            return
        self._queued.append(row)
        self._pending.add()
        await self._pump()

    async def _pump(self) -> None:
        while len(self._running) < self.slots:
            i = next_reading(self._queued, list(self._running.values()))
            if i is None:
                return
            row = self._queued.pop(i)
            self._running[_identity(row)] = row.team
            await background.start(self._background(row), key=READING_PROCESS)

    async def _background(self, row: ReadingRow) -> None:
        """One reading on the supervisor: a failure is raised to it (logged, shown on /health/background) after the
        next queued reading is started from here. A cancelled one (the process stopping) starts nothing, and what is
        still queued is left to `resume` after the restart."""
        try:
            with isolation.scope(row.tenant_id, row.team):
                await (self._retry(row) if row.status == "done" else self._run(row))
        except asyncio.CancelledError:
            self._running.pop(_identity(row), None)
            self._pending.done(1 + len(self._queued))
            self._queued.clear()
            raise
        except Exception:
            await self._finished(row)
            raise
        await self._finished(row)

    async def _finished(self, row: ReadingRow) -> None:
        self._running.pop(_identity(row), None)
        self._pending.done()
        await self._pump()

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
        settings, wanted, sensitivity = key_parts(row.key)
        started = time.perf_counter()
        stack = ExitStack()
        try:
            reader = await asyncio.to_thread(self._open, stack, data, file, settings)
            total = reader.facts.page_count
            await self.store.opened(row, pages_total=total, facts=reader.facts.model_dump(mode="json", by_alias=True))
            described = await self._described_so_far(row)
            retry = False
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
                passing = False
                if self.pictures is not None and wanted and wants_picture(page, reader.facts.mime_type):
                    try:
                        page, passing = await asyncio.wait_for(
                            self.pictures.describe(
                                page, data=data, mime=reader.facts.mime_type, used=described, sensitivity=sensitivity,
                                tenant=row.tenant_id, run=f"reading:{row.digest[:24]}",
                            ),
                            self.page_timeout_s,
                        )  # fmt: skip
                    except TimeoutError:
                        page, passing = not_described(page, "the model took too long"), False
                    described += page.source == "model"
                    retry |= passing
                retries = 1 if passing else None
                await self.store.save_page(row, number, page.model_dump(mode="json", by_alias=True), retries=retries)
            took = round((time.perf_counter() - started) * 1000)
            done = await self.store.get(row.team, row.digest, row.version, row.key)
            await self.store.finish(
                done or row,
                status="done",
                at=self.clock(),
                duration_ms=took,
                error_code=RETRY_PICTURES if retry else None,
            )
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

    async def _retry(self, row: ReadingRow) -> None:
        """Describes again only the pages whose picture was refused for a reason that passes; every other page is kept.
        A page refused again counts one more try, and after PICTURE_RETRIES it keeps its note for good."""
        assert self.pictures is not None
        who = Who(tenant_id=row.tenant_id, team=row.team, actor=row.actor)
        level = key_parts(row.key)[2]
        try:
            file = await self.files.readable(who, row.file_id)
            data = await self.files.read(who, file)
        except (FileMissingError, FileNotReadyError):
            return  # kept as it is; an ask after the next wait tries again
        if level is None or row.facts is None:
            return
        level = stricter(level, file.sensitivity)
        mime = FileFacts.model_validate(row.facts).mime_type
        described, waiting = await self.store.pages_to_retry(row)
        redone: list[tuple[Page, int | None]] = []
        for page, tries in waiting:
            before = as_read(page)
            try:
                after, passing = await asyncio.wait_for(
                    self.pictures.describe(
                        before, data=data, mime=mime, used=described, sensitivity=level, tenant=row.tenant_id,
                        run=f"reading:{row.digest[:24]}",
                    ),
                    self.page_timeout_s,
                )  # fmt: skip
            except TimeoutError:
                after, passing = not_described(before, "the model took too long"), False
            described += after.source == "model"
            redone.append((after, tries + 1 if passing and tries < PICTURE_RETRIES else None))
        waits = any(tries is not None for _, tries in redone)
        changed = any(page.source == "model" for page, _ in redone)
        await self.store.retried(row, redone, code=RETRY_PICTURES if waits else None, at=self.clock(), changed=changed)

    async def _described_so_far(self, row: ReadingRow) -> int:
        """Pages of this reading a model already described, so a reading resumed after a restart keeps its limit."""
        if self.pictures is None or not key_parts(row.key)[1] or row.pages_done == 0:
            return 0
        pages = await self.store.pages(row.team, row.digest, row.version, row.key)
        return sum(p.source == "model" for p in pages)

    @staticmethod
    def _open(stack: ExitStack, data: bytes, file: FileInfo, settings: ReadingSettings) -> FileReader:
        return stack.enter_context(open_file(data, filename=file.name, mime_type=file.mime, settings=settings))
