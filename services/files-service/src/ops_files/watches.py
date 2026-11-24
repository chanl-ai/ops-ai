"""The check of a watched folder: list what changed since the watch's place through ops_sources, fetch the changed
files a few at once, write each as its file's next version with its event in the version's own transaction, and number
what it found as the watch's events.

A check holds the watch's lease from start to end, so Check now while one runs answers "already checking" and two
background workers never check one watch at once. Files keeps the place on the watch and each file's marker on its
entry (`FileState`). Fetched bytes are held a few files at a time (`CHUNK`), never the whole check's. A file listed as
too large, or refused at fetch for its size, is one failed event with its size, and an entry already held for it is
not removed; a file a folder's rule leaves out is no event. A fetch refused for another reason is one failed event
for that version: the check ends partial so the next lists it again, on up to FETCH_TRIES checks, and then the file is
left (kept, and not fetched) until it changes at the source, so the check settles. A rate limit ends it partial;
tools-service out of reach ends it refused. Only a check that ends success moves the place on, so the next check lists
the same changes again. Only a full listing read whole removes the files it did not list. A check that loses its
lease (saving its place, renewing it, or writing a version) stops at once."""

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

from sqlalchemy.ext.asyncio import AsyncConnection

from ops_files.store import FilesStore, HeldSource, WatchesStore, WatchEvent, WatchRow
from ops_files.store.watches import LeaseLost, link_new_events, write_events
from ops_files.tenant_files import TenantFiles
from ops_identity import ServiceCallError, ServiceUnreachable
from ops_service_kit.errors import Conflict
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.ids import new_id
from ops_sources import Answer, Declared, Fetcher, Held, Listing, Place, Reader, SourceError, read_changes
from ops_sources.contract import RECONNECT, access_list
from ops_store import background, isolation

log = logging.getLogger(__name__)

KEY = "files_watch_checks"
# Changed files fetched and held in memory at once; each is written before the next few are fetched.
CHUNK = 4
# How long a check's lease lasts before it is renewed (between chunks); a check whose process died frees it then.
LEASE_S = 300.0
# Error codes a fetch answers for a file larger than the gateway carries.
TOO_LARGE = {"TOO_LARGE", "RESPONSE_TOO_LARGE", "PAYLOAD_TOO_LARGE"}
# The largest file a fetch brings in: tools-service refuses an app's answer over 25 MB (MAX_RESPONSE_BYTES). A file
# the listing called smaller (its size changed, or the app gave none) is refused at fetch with the listing's words.
FETCH_LIMIT_MB = 25


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
        """Saves the place after each page, renewing the lease; a check that lost its lease stops here."""
        kept = await self.watches.save_place(
            self.watch.id,
            owner=self.owner,
            place=cast(dict[str, JsonValue], dataclasses.asdict(place)),
            seconds=LEASE_S,
        )
        if not kept:
            raise LeaseLost(self.watch.id)

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


# Failed files a check's outcome names on the watch's row; the rest are in its events.
FAILURES_KEPT = 20


@dataclass
class CheckOutcome:
    status: str
    brought: int = 0
    failed: int = 0
    removed: int = 0
    stopped: str = ""
    # Why a check was refused or stopped partial (needs_reconnect, unreachable, rate_limited, fetch_failed, ...), so
    # the console says the actual reason; empty on a success.
    code: str = ""
    # The first failed files ({path, size, reason}), so the Watched folders row says which file failed and why.
    failures: list[dict[str, JsonValue]] = dataclasses.field(default_factory=list[dict[str, JsonValue]])

    def fail(self, event: WatchEvent) -> None:
        self.failed += 1
        if len(self.failures) < FAILURES_KEPT:
            self.failures.append(
                {"path": event["path"], "size": event["size"], "reason": event["reason"], "code": event["code"]}
            )

    def as_json(self) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], dataclasses.asdict(self))


def _bytes_of(item: Json) -> bytes:
    content = item.get("content")
    if not isinstance(content, str):
        return b""
    return base64.b64decode(content) if item.get("encoding") == "base64" else content.encode()


def _changed_at(row: Json) -> datetime | None:
    """The listing's modified time for the file; None when it gave none or one that does not read as a time."""
    at = row.get("updated_at")
    if not isinstance(at, str) or not at:
        return None
    try:
        found = datetime.fromisoformat(at)
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=UTC)


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
        outcome = CheckOutcome("failed", code="stopped", stopped="The check stopped before it finished.")
        try:
            outcome = await self._run(watch_id, owner)
        except LeaseLost:
            # It ran past its lease and another check took the folder; that check's writes are the ones kept.
            outcome = CheckOutcome("failed", code="lease_lost", stopped="Another check took this folder over.")
        finally:
            await self.watches.finish(watch_id, owner=owner, outcome=outcome.as_json(), at=self.clock())
        return outcome

    async def _run(self, watch_id: str, owner: str) -> CheckOutcome:
        watch = await self.watches.get(watch_id)
        if watch is None:
            return CheckOutcome("failed", code="gone", stopped="The watch is gone.")
        tenant, team = watch.tenant_id, watch.team
        try:
            declared = await self.reader.declared(tenant, team)
        except (ServiceUnreachable, ServiceCallError) as e:
            return CheckOutcome("refused", code="unreachable", stopped=f"Apps could not be reached: {e}")
        row = next((d for d in declared if (d.get("plugin"), d.get("source")) == (watch.plugin, watch.source)), None)
        if row is None:
            return CheckOutcome(
                "refused", code="not_installed", stopped=f"{watch.plugin} is not installed or is off for this team."
            )
        found = Declared.model_validate(row)
        tools = found.tools
        state = FileState(self.store, self.watches, watch, owner)
        await state.load()
        place = Place(**cast(dict[str, object], watch.place)) if watch.place else Place()  # pyright: ignore[reportArgumentType]
        counts = {"listed": 0, "unchanged": 0, "skipped": 0, "failed": 0}
        gets = _Gets(self.reader, tools.get)
        refused = await self.watches.refused_sizes(watch_id)
        refused_before = dict(refused)
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
            return CheckOutcome("refused", code="unreachable", stopped=f"Apps could not be reached: {e}")
        except Conflict as e:
            # The connection refused its sign-in on an earlier check and is still not healthy.
            if e.code != "needs_reconnect":
                raise
            return CheckOutcome("refused", code="needs_reconnect", stopped=str(e))
        code = _listing_code(listing)
        if listing.status in ("failed", "skipped") and not listing.seen:
            await state.save(place)
            return CheckOutcome("refused", code=code, stopped=listing.stopped)
        ok = listing.status == "success"
        outcome = CheckOutcome("success" if ok else listing.status, code="" if ok else code, stopped=listing.stopped)
        failed: list[WatchEvent] = []
        now = self.clock()
        by_row = {str(r["id"]): r for r in listing.changed}
        # The new entries of this check by their bytes, to tell a file moved or renamed at the source from a new one.
        new_by_digest: dict[str, list[str]] = {}

        async def on_item(r: Json, item: Json) -> None:
            source_id = str(r["id"])
            content = _bytes_of(item)
            before = state.by_id.get(source_id)
            path = str(item.get("folder") or r.get("folder") or "").strip("/")
            name = str(item.get("title") or r.get("title") or source_id)
            full_path = f"{path}/{name}" if path else name

            async def then(c: AsyncConnection, file_id: str, version: int | None) -> None:
                # The version and its event commit together, and only while this check holds the lease.
                if version is not None:
                    kind = "new" if version == 1 else "changed"
                    if version == 1:
                        new_by_digest.setdefault(hashlib.sha256(content).hexdigest(), []).append(file_id)
                    events = [_event(file_id, version, kind, None, len(content), full_path, now)]
                elif before is not None and before.name != name:
                    events = [_event(file_id, None, "renamed", None, len(content), full_path, now)]
                else:
                    events = []
                await write_events(c, watch.id, owner=owner, events=events)

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
                    "changed_at": _changed_at(r),
                },
                content,
                actor=f"watch:{watch.id}",
                then=then,
            )
            state.by_id[source_id] = HeldSource(file_id, str(r.get("marker") or ""), None, 0, name, False)
            refused.pop(source_id, None)
            if version is not None:
                outcome.brought += 1

        # Every file the listing refused is kept from removal; only a refusal for its size is a failed event, since a
        # file a folder's rule leaves out was never meant to come in.
        # A file refused for its size is said once per version: listed again at the size and version tag it was
        # refused at, it is neither a new event nor fetched again; an edit at the same size is a new tag.
        skipped_ids: set[str] = set()
        for r in listing.skipped:
            skipped_ids.add(str(r["id"]))
            if r.get("skipped_code") not in TOO_LARGE:
                continue
            held = state.by_id.get(str(r["id"]))
            reason = str(r.get("skipped") or "") or "Too large to bring in"
            event = _event(
                held.file_id if held else None, None, "failed", reason, _size_of(r), _title(r), now, code="too_large"
            )
            outcome.fail(event)
            if _said(refused, str(r["id"]), _seen_as(r)):
                failed.append(event)
        for r in listing.changed:
            if (seen := _seen_as(r)) is not None and refused.get(str(r["id"])) == seen:
                skipped_ids.add(str(r["id"]))
        if skipped_ids & {str(r["id"]) for r in listing.changed}:
            listing = dataclasses.replace(
                listing, changed=[r for r in listing.changed if str(r["id"]) not in skipped_ids]
            )
        by_row = {str(r["id"]): r for r in listing.changed}
        gone_now: list[str] = []
        errors: list[SourceError] = []
        for start in range(0, len(listing.changed), CHUNK):
            part = dataclasses.replace(listing, changed=listing.changed[start : start + CHUNK])
            fetcher = Fetcher(gets, state, tools, part, tenant=tenant, team=team, act="watch")
            done = await fetcher.fetch_changed(
                place, counts, errors, listing.log, on_listed=on_item, on_fetched=on_item, final=TOO_LARGE
            )
            gone_now += done.gone_now
            stop = False
            for source_id, answer in gets.failed.items():
                if answer.code == "UPSTREAM_UNREACHABLE":
                    # Nothing was refused: the next check lists the same changes again and fetches them.
                    outcome.status, outcome.code = "refused", "unreachable"
                    outcome.stopped, stop = f"Apps could not be reached: {answer.message or answer.code}", True
                    continue
                if answer.code == "RATE_LIMITED":
                    if outcome.status == "success":
                        outcome.status, outcome.code = "partial", "rate_limited"
                        outcome.stopped = "Stopped at the system's rate limit; the next check continues."
                    stop = True
                    continue
                reason, code = answer.message or answer.code, "fetch_failed"
                if answer.code in TOO_LARGE:
                    reason, code = f"Larger than {FETCH_LIMIT_MB} MB", "too_large"
                elif source_id in done.retrying and outcome.status == "success":
                    # A file that could not be fetched for another reason is tried again on the next check.
                    outcome.status, outcome.code = "partial", "fetch_failed"
                    outcome.stopped = "Some files could not be fetched; the next check tries them again."
                skipped_ids.add(source_id)
                held = state.by_id.get(source_id)
                r = by_row.get(source_id, {})
                event = _event(
                    held.file_id if held else None,
                    None,
                    "failed",
                    reason,
                    _size_of(r),
                    _title(r, source_id),
                    now,
                    code=code,
                )
                outcome.fail(event)
                # One failed event per version: a check that tries it again names it on the row, not as a new event.
                if code == "too_large":
                    if _said(refused, source_id, _seen_as(r)):
                        failed.append(event)
                elif source_id in done.failed_first:
                    failed.append(event)
            gets.failed.clear()
            if failed and not await self.watches.add_events(watch.id, owner=owner, events=failed):
                raise LeaseLost(watch.id)
            failed = []
            if not await self.watches.renew(watch.id, owner=owner, seconds=LEASE_S):
                raise LeaseLost(watch.id)
            if stop:
                break
        if failed and not await self.watches.add_events(watch.id, owner=owner, events=failed):
            raise LeaseLost(watch.id)
        removed = set(listing.removed_at_source) | set(gone_now)
        if listing.full and listing.whole and outcome.status == "success":
            # Only a full listing read whole sees every file; one listed but refused (too large) is not removed.
            removed |= {i for i in state.by_id if i not in listing.seen and i not in skipped_ids}
        gone = [state.by_id[i] for i in removed if i in state.by_id and not state.by_id[i].removed]

        links = _links(
            await self.store.digests([h.file_id for h in gone]) if gone and new_by_digest else {}, new_by_digest
        )

        async def removals(c: AsyncConnection) -> None:
            events = [_event(h.file_id, None, "removed", None, None, h.name, now) for h in gone]
            await write_events(c, watch.id, owner=owner, events=events)
            await link_new_events(c, watch.id, links)

        await self.store.remove_sources([h.file_id for h in gone], now, then=removals)
        outcome.removed = len(gone)
        if listing.full and listing.whole:
            # A file no longer listed is forgotten, so it is said again if it comes back.
            listed = set(listing.seen) | skipped_ids
            refused = {i: n for i, n in refused.items() if i in listed}
        if refused != refused_before and not await self.watches.save_refused_sizes(
            watch.id, owner=owner, sizes=refused
        ):
            raise LeaseLost(watch.id)
        listing.settle(place, outcome.status)
        await state.save(place)
        return outcome

    async def run_asked(self) -> int:
        """Every watch with a check asked for, each in its own tenant and team; the number checked. A check that
        raises is logged and the pass goes on to the next watch."""
        done = 0
        for tenant, team, watch_id in await self.watches.asked():
            with isolation.scope(tenant, team):
                try:
                    outcome = await self.check(watch_id)
                except Exception:
                    log.exception("watch check failed", extra={"watch_id": watch_id, "tenant_id": tenant})
                    done += 1
                    continue
            done += outcome.status != "already_checking"
        return done


def _title(r: Json, fallback: str = "") -> str:
    return str(r.get("title") or r.get("id") or fallback)


def _listing_code(listing: Listing) -> str:
    """Why a listing stopped, as the code a refused or partial outcome carries; the console words it."""
    error = str(listing.errors[-1].get("errorClass") or "") if listing.errors else ""
    if error in RECONNECT:
        return "needs_reconnect"
    if error == "UPSTREAM_UNREACHABLE":
        return "unreachable"
    if error == "RATE_LIMITED":
        return "rate_limited"
    if error == "APP_OFF_FOR_TEAM":
        return "app_off"
    if error == "PLUGIN_DISABLED":
        return "not_installed"
    if listing.resumes:
        return "continues"
    return "list_failed" if listing.status != "success" else ""


def _seen_as(r: Json) -> str | None:
    """The file as a listing saw it, its size and version tag; None when the listing gave no size."""
    size = _size_of(r)
    return None if size is None else f"{size}:{r.get('marker') or ''}"


def _said(refused: dict[str, str], source_id: str, seen: str | None) -> bool:
    """True, remembering how it was seen, when a size refusal of this version of the file has not been said."""
    if seen is not None and refused.get(source_id) == seen:
        return False
    refused[source_id] = seen or ""
    return True


def _links(removed: dict[str, str], new_by_digest: dict[str, list[str]]) -> dict[str, str]:
    """{new file id: removed file id} for each digest held by exactly one removed entry and exactly one new entry; two
    copies of the same bytes, on either side, link nothing, since which one moved cannot be told."""
    old_by_digest: dict[str, list[str]] = {}
    for file_id, digest in removed.items():
        old_by_digest.setdefault(digest, []).append(file_id)
    return {
        new[0]: old[0]
        for digest, old in old_by_digest.items()
        if len(old) == 1 and len(new := new_by_digest.get(digest, [])) == 1
    }


def _event(  # noqa: PLR0917 - one event row, every column given
    file_id: str | None,
    version: int | None,
    kind: str,
    reason: str | None,
    size: int | None,
    path: str,
    at: datetime,
    *,
    code: str | None = None,
) -> WatchEvent:
    return cast(
        WatchEvent,
        {
            "file_id": file_id,
            "version": version,
            "kind": kind,
            "reason": (reason or None) and reason[:500],
            "code": code,
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
