"""The check of a watched folder: list what changed since the watch's place through ops_sources, fetch the changed
files a few at once, write each as its file's next version, and number what it found as the watch's events.

A check holds the watch's lease from start to end, so Check now while one runs answers "already checking" and two
background workers never check one watch at once. Files keeps the place on the watch and each file's marker on its
entry (`FileState`). Fetched bytes are held a few files at a time (`CHUNK`), never the whole check's. A file listed as
too large, or refused at fetch for its size, is one failed event with its size, and an entry already held for it is
not removed. When tools-service cannot be reached, the check ends refused, its place unchanged."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from ops_files.store import FilesStore, HeldSource, WatchesStore, WatchEvent, WatchRow
from ops_files.tenant_files import TenantFiles
from ops_identity import ServiceCallError, ServiceUnreachable
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.ids import new_id
from ops_sources import Answer, Declared, Fetcher, Held, Place, Reader, SourceError, read_changes
from ops_sources.contract import access_list
from ops_store import background, isolation

log = logging.getLogger(__name__)

KEY = "files_watch_checks"
# Changed files fetched and held in memory at once; each is written before the next few are fetched.
CHUNK = 4
# How long a check's lease lasts before it is renewed (between chunks); a check whose process died frees it then.
LEASE_S = 300.0
# Error codes a fetch answers for a file larger than the gateway carries.
TOO_LARGE = {"TOO_LARGE", "RESPONSE_TOO_LARGE", "PAYLOAD_TOO_LARGE"}


def source_key(connection_id: str | None, source_id: str) -> str:
    """One entry per source file of a connection: a rename keeps the source's id, so it keeps the entry."""
    return hashlib.sha256(f"{connection_id or ''}\0{source_id}".encode()).hexdigest()


class FileState:
    """ops_sources' state port on a watch: the place on the watch row, each held file's marker on its entry."""

    def __init__(self, files: FilesStore, watches: WatchesStore, watch: WatchRow, owner: str) -> None:
        self.files, self.watches, self.watch, self.owner = files, watches, watch, owner
        self.by_id: dict[str, HeldSource] = {}

    async def load(self) -> None:
        self.by_id = await self.files.held_sources(self.watch.team, self.watch.id)

    def held(self, item_id: str) -> Held | None:
        h = self.by_id.get(item_id)
        if h is None or h.removed:
            return None
        return Held(marker=h.marker, tag=h.tag, current=True, gone_count=h.gone_count, title=h.name)

    async def save(self, place: Place) -> None:
        await self.watches.save_place(
            self.watch.id, owner=self.owner, place=cast(dict[str, JsonValue], dataclasses.asdict(place))
        )

    async def mark(self, item_id: str, marker: str) -> None:
        if (h := self.by_id.get(item_id)) is not None:
            await self.files.mark_source(h.file_id, marker=marker)
            self.by_id[item_id] = h._replace(marker=marker)

    async def gone(self, item_id: str, count: int) -> None:
        if (h := self.by_id.get(item_id)) is not None:
            await self.files.mark_source(h.file_id, marker=h.marker, gone_count=count)
            self.by_id[item_id] = h._replace(gone_count=count)


class _Gets:
    """The reader, with each failed fetch kept by the file's id, so a refused file becomes its own failed event."""

    def __init__(self, reader: Reader, get_tool: str | None) -> None:
        self.reader, self.get_tool = reader, get_tool
        self.failed: dict[str, Answer] = {}

    async def declared(self, tenant_id: str, team_id: str) -> list[dict[str, JsonValue]]:
        return await self.reader.declared(tenant_id, team_id)

    async def call(
        self, tenant_id: str, team_id: str, tool: str | None, args: dict[str, JsonValue], *, act: str
    ) -> Answer:
        answer = await self.reader.call(tenant_id, team_id, tool, args, act=act)
        if tool == self.get_tool and not answer.ok and answer.code != "NOT_FOUND":
            self.failed[str(args.get("id"))] = answer
        return answer


@dataclass
class CheckOutcome:
    status: str
    brought: int = 0
    failed: int = 0
    removed: int = 0
    stopped: str = ""

    def as_json(self) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], dataclasses.asdict(self))


def _bytes_of(item: Json) -> bytes:
    content = item.get("content")
    if not isinstance(content, str):
        return b""
    return base64.b64decode(content) if item.get("encoding") == "base64" else content.encode()


def _size_of(row: Json) -> int | None:
    size = row.get("size")
    return int(size) if isinstance(size, int | float) else None


class WatchChecks:
    """Checks watched folders for files-service: one check per watch at a time, under its lease."""

    def __init__(
        self, files: TenantFiles, reader: Reader, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self.files, self.reader, self.clock = files, reader, clock
        self.store = FilesStore(files.engine)
        self.watches = WatchesStore(files.engine)

    async def check(self, watch_id: str) -> CheckOutcome:
        """One check of a watch in the current tenant and team; "already checking" when another holds its lease."""
        owner = new_id("chk")
        if not await self.watches.claim(watch_id, owner=owner, seconds=LEASE_S):
            return CheckOutcome("already_checking", stopped="A check of this folder is already running.")
        outcome = CheckOutcome("failed", stopped="The check stopped before it finished.")
        try:
            outcome = await self._run(watch_id, owner)
        finally:
            await self.watches.finish(watch_id, owner=owner, outcome=outcome.as_json(), at=self.clock())
        return outcome

    async def _run(self, watch_id: str, owner: str) -> CheckOutcome:
        watch = await self.watches.get(watch_id)
        if watch is None:
            return CheckOutcome("failed", stopped="The watch is gone.")
        tenant, team = watch.tenant_id, watch.team
        try:
            declared = await self.reader.declared(tenant, team)
        except (ServiceUnreachable, ServiceCallError) as e:
            return CheckOutcome("refused", stopped=f"Apps could not be reached: {e}")
        row = next((d for d in declared if (d.get("plugin"), d.get("source")) == (watch.plugin, watch.source)), None)
        if row is None:
            return CheckOutcome("refused", stopped=f"{watch.plugin} is not installed or is off for this team.")
        found = Declared.model_validate(row)
        tools = found.tools
        state = FileState(self.store, self.watches, watch, owner)
        await state.load()
        place = Place(**cast(dict[str, object], watch.place)) if watch.place else Place()  # pyright: ignore[reportArgumentType]
        counts = {"listed": 0, "unchanged": 0, "skipped": 0, "failed": 0}
        gets = _Gets(self.reader, tools.get)
        try:
            listing = await read_changes(
                gets,
                state,
                place,
                tools,
                tenant=tenant,
                team=team,
                values=watch.values,
                connection_id=watch.connection_id,
                full=False,
                trigger="schedule",
                act="watch",
                counts=counts,
                clock=self.clock,
            )
        except (ServiceUnreachable, ServiceCallError) as e:
            return CheckOutcome("refused", stopped=f"Apps could not be reached: {e}")
        if listing.status in ("failed", "skipped") and not listing.seen:
            await state.save(place)
            return CheckOutcome("refused", stopped=listing.stopped)
        outcome = CheckOutcome("success" if listing.status == "success" else listing.status, stopped=listing.stopped)
        events: list[WatchEvent] = []
        now = self.clock()
        by_row = {str(r["id"]): r for r in listing.changed}

        async def on_item(r: Json, item: Json) -> None:
            source_id = str(r["id"])
            content = _bytes_of(item)
            before = state.by_id.get(source_id)
            path = str(item.get("folder") or r.get("folder") or "").strip("/")
            name = str(item.get("title") or r.get("title") or source_id)
            full_path = f"{path}/{name}" if path else name
            file_id, version = await self.files.put_source(
                tenant,
                team,
                {
                    "key_hash": source_key(watch.connection_id, source_id),
                    "source_id": source_id,
                    "source_path": full_path,
                    "name": name,
                    "mime": str(item.get("mime") or "application/octet-stream"),
                    "access_list": access_list(item),
                    "access_read_at": now,
                    "watch_id": watch.id,
                    "marker": str(item.get("marker") or r.get("marker") or "") or None,
                },
                content,
                actor=f"watch:{watch.id}",
            )
            state.by_id[source_id] = HeldSource(file_id, str(r.get("marker") or ""), None, 0, name, False)
            if version is None:
                if before is not None and before.name != name:
                    events.append(_event(file_id, None, "renamed", None, len(content), full_path, now))
                return
            kind = "new" if version == 1 else "changed"
            events.append(_event(file_id, version, kind, None, len(content), full_path, now))
            outcome.brought += 1

        skipped_ids: set[str] = set()
        for r in listing.skipped:
            skipped_ids.add(str(r["id"]))
            held = state.by_id.get(str(r["id"]))
            events.append(
                _event(
                    held.file_id if held else None,
                    None,
                    "failed",
                    str(r.get("skipped") or ""),
                    _size_of(r),
                    str(r.get("title") or r["id"]),
                    now,
                )
            )
            outcome.failed += 1
        gone_now: list[str] = []
        errors: list[SourceError] = []
        for start in range(0, len(listing.changed), CHUNK):
            part = dataclasses.replace(listing, changed=listing.changed[start : start + CHUNK])
            fetcher = Fetcher(gets, state, tools, part, tenant=tenant, team=team, act="watch")
            done = await fetcher.fetch_changed(
                place, counts, errors, listing.log, on_listed=on_item, on_fetched=on_item
            )
            gone_now += done.gone_now
            if done.rate_limited:
                outcome.status, outcome.stopped = "partial", "Stopped at the system's rate limit."
            await self.watches.renew(watch.id, owner=owner, seconds=LEASE_S)
        for source_id, answer in gets.failed.items():
            r = by_row.get(source_id, {})
            held = state.by_id.get(source_id)
            reason = answer.message or answer.code
            if answer.code in TOO_LARGE:
                reason = f"Too large to bring in: {reason}"
            skipped_ids.add(source_id)
            events.append(
                _event(
                    held.file_id if held else None,
                    None,
                    "failed",
                    reason,
                    _size_of(r),
                    str(r.get("title") or source_id),
                    now,
                )
            )
            outcome.failed += 1
        removed = set(listing.removed_at_source) | set(gone_now)
        if listing.whole and listing.status == "success":
            # Only a listing read whole sees every file; one listed but refused (too large) is not removed.
            removed |= {i for i in state.by_id if i not in listing.seen and i not in skipped_ids}
        gone = [state.by_id[i] for i in removed if i in state.by_id and not state.by_id[i].removed]
        await self.store.remove_sources([h.file_id for h in gone], now)
        events += [_event(h.file_id, None, "removed", None, None, h.name, now) for h in gone]
        outcome.removed = len(gone)
        await self.watches.add_events(watch.id, owner=owner, events=events)
        listing.settle(place, "success" if outcome.status == "success" else outcome.status)
        await state.save(place)
        return outcome

    async def run_asked(self) -> int:
        """Every watch with a check asked for, each in its own tenant and team; the number checked."""
        done = 0
        for tenant, team, watch_id in await self.watches.asked():
            with isolation.scope(tenant, team):
                outcome = await self.check(watch_id)
            done += outcome.status != "already_checking"
        return done


def _event(  # noqa: PLR0917 - one event row, every column given
    file_id: str | None, version: int | None, kind: str, reason: str | None, size: int | None, path: str, at: datetime
) -> WatchEvent:
    return cast(
        WatchEvent,
        {
            "file_id": file_id,
            "version": version,
            "kind": kind,
            "reason": (reason or None) and reason[:500],
            "size": size,
            "path": path[:1024],
            "at": at,
        },
    )


async def keep_checking(
    checks: WatchChecks, stop: asyncio.Event | None = None, *, every_s: float | None = None
) -> None:
    """The listed `files_watch_checks` process: every few seconds it runs the checks people asked for."""

    async def run(_tx: background.Tx, _now: float) -> int:
        return await checks.run_asked()

    background.give_pass(KEY, run, service="files")
    await background.run_sweep(KEY, stop=stop or asyncio.Event(), every_s=every_s)


__all__ = ["CHUNK", "KEY", "CheckOutcome", "FileState", "WatchChecks", "keep_checking", "source_key"]
