# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Changes since a place, with every page read.

A run lists the changed items page by page from the saved place, saving it after each page, and compares each item's
marker with what is held, so only items whose marker moved are fetched. A full listing (the first, after a week, or
every run of a source that lists whole) sees every item, so the reading service can remove what was not listed. A
rate limit ends the run partial and the next resumes from the saved page; a saved page the system no longer honours
restarts the listing once; a refused sign-in pauses the source until its connection is healthy again."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ops_service_kit.errors import Conflict
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.narrow import json_object

from .contract import RECONNECT, SourceError, SourceTools, listing_of
from .state import Place, Reader, SourceState

# Pages one run reads before it stops partial and saves its place, so a listing that never ends cannot hold a run.
MAX_PAGES = 200
# A listing refused for its saved page: the system dropped it (a query locator expires), or the gateway's seal no
# longer opens it. The run starts the listing again from the watermark instead of failing every run on it.
STALE_CURSOR = {"INVALID_INPUT", "INVALID_ARGUMENTS"}
FULL_EVERY = timedelta(days=7)
# A tool that gives no watermark: the next run lists from the newest change seen, less this, so a record saved during
# a run is listed again rather than missed.
OVERLAP = timedelta(minutes=5)


@dataclass
class Listing:
    """What one run's listing found, for the fetch and for the reading service's removals."""

    started: datetime
    # Read from the first page of a full listing (or finishing one carried over runs): every item was seen.
    full: bool
    whole: bool
    # Stopped at the page cap: the next run lists on from the saved place.
    resumes: bool = False
    status: str = "success"
    stopped: str = ""
    seen: set[str] = field(default_factory=set[str])
    # Items whose marker moved, each with its marker set, to fetch (or to keep when the listing carried content).
    changed: list[Json] = field(default_factory=list[Json])
    removed_at_source: list[str] = field(default_factory=list[str])
    watermark: str | None = None
    # Seconds between two fetches: the source's own rate, or the slower pace its listing names.
    pace: float = 0.0
    errors: list[SourceError] = field(default_factory=list[SourceError])
    log: list[str] = field(default_factory=list[str])
    # The source's own settings, sent to every call as `source`.
    given: Json = field(default_factory=dict[str, JsonValue])

    def settle(self, place: Place, status: str) -> None:
        """After a run that ended `status`: a finished listing moves the place on to its watermark."""
        if status == "success":
            place.watermark = self.watermark
            place.cursor = None
            if self.full:
                place.last_full_at = self.started.isoformat()


def _less_overlap(stamp: str) -> str:
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return stamp
    return f"{(when - OVERLAP).astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}"


async def read_changes(
    reader: Reader,
    state: SourceState,
    place: Place,
    tools: SourceTools,
    *,
    tenant: str,
    team: str,
    values: JsonValue,
    connection_id: JsonValue,
    full: bool,
    trigger: str,
    act: str,
    counts: dict[str, int],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    max_pages: int = MAX_PAGES,
    full_every: timedelta = FULL_EVERY,
) -> Listing:
    """List what changed since `place`, page by page, saving the place after each page through `state`. `trigger`
    "full" ignores a saved page. Counts `listed`, `unchanged` and `skipped` into `counts`."""
    if place.paused == "needs_reconnect":
        healthy = any(
            d.get("connectionId") == connection_id and d.get("connectionStatus") == "healthy"
            for d in await reader.declared(tenant, team)
        )
        if not healthy:
            raise Conflict(
                "The connection refused its sign-in. Reconnect it and run Test connection, then sync again.",
                code="needs_reconnect",
            )
        place.paused = None
    started = clock()
    last_full = place.last_full_at
    full = (
        full
        or tools.lists_whole
        or not place.watermark
        or not last_full
        or started - datetime.fromisoformat(last_full) > full_every
    )
    since = None if full else place.watermark
    cursor = place.cursor if trigger != "full" else None
    # The source's own settings go to every call; an incremental run lists only what changed when the plugin has a
    # changes tool and a cursor from the last run, else lists from the watermark.
    given: Json = {"source": values} if values else {}
    by_changes = bool(not full and tools.changes and place.changes_cursor)
    if by_changes:
        list_tool = str(tools.changes)
    elif tools.list is not None:
        list_tool = tools.list
    else:
        raise KeyError("listTool")
    if by_changes and not cursor:
        cursor = place.changes_cursor
    tombstones = place.tombstones
    # Only a listing read from its first page sees every item, so only then is an unseen item removed. One longer than a
    # run's pages carries what it listed so far (`seen_so_far`) into the run that finishes it.
    from_start = cursor is None
    carried = set(place.seen_so_far or []) if cursor else set[str]()
    whole = from_start or place.seen_so_far is not None
    if from_start:
        place.seen_so_far = None
    found = Listing(started=started, full=full, whole=whole, given=given)
    seen, changed, log, errors = found.seen, found.changed, found.log, found.errors
    newest: str | None = None

    pages, restarted = 0, False
    # The seconds between two fetches of this source's items: the source's own rate, or the slower pace its listing
    # names (a site's robots.txt Crawl-delay). Each fetch is its own call, so the plugin cannot pace them itself.
    rate = json_object(values).get("rate")
    pace = 1.0 / float(rate) if isinstance(rate, int | float) and rate > 0 else 0.0
    while True:
        if pages >= max_pages:
            # The items listed so far are fetched now; the next run lists on from the saved cursor.
            found.status = "partial"
            found.stopped = f"Listed {max_pages} pages; the next run continues the listing from here."
            found.resumes = True
            if whole:
                place.seen_so_far = sorted(carried | seen)
            break
        asked = {k: v for k, v in (("since", None if by_changes else since), ("cursor", cursor)) if v}
        page = await reader.call(tenant, team, list_tool, {**given, **asked}, act=act)
        pages += 1
        if not page.ok and cursor and not restarted and page.code in STALE_CURSOR:
            restarted, cursor = True, None
            place.cursor = None
            place.seen_so_far = None
            carried, whole = set[str](), True
            found.whole = True
            await state.save(place)
            continue
        if not page.ok:
            if page.code == "RATE_LIMITED":
                found.status = "partial"
                found.stopped = "Stopped at the system's rate limit; the next run continues from here."
            elif page.code in RECONNECT:
                found.status, found.stopped = "failed", "The connection refused its sign-in; reconnect it."
                place.paused = "needs_reconnect"
            elif page.code == "APP_OFF_FOR_TEAM":
                found.status, found.stopped = "skipped", "The plugin is off for this team."
            elif page.code == "PLUGIN_DISABLED":
                found.status, found.stopped = "skipped", "The plugin is not installed on this system."
            else:
                found.status, found.stopped = "failed", page.message or page.code
            errors.append({"phase": "list", "errorClass": page.code, "message": page.message or page.code})
            break
        rows = listing_of(page.output)
        if rows is None:
            found.status, found.stopped = "failed", "The tool's answer is not a knowledge listing."
            errors.append({"phase": "list", "errorClass": "contract", "message": found.stopped})
            break
        out = json_object(page.output)
        named = out.get("pace_s")
        if isinstance(named, int | float):
            pace = max(pace, float(named))
        for r in rows:
            item_id = str(r["id"])
            counts["listed"] += 1
            seen.add(item_id)
            newest = max(newest or "", str(r["updated_at"]))
            marker = str(r.get("marker") or r["updated_at"])
            if r.get("deleted"):
                found.removed_at_source.append(item_id)
                continue
            if item_id in tombstones:
                # Removed after answering gone twice: a link elsewhere does not bring it back until it is lifted.
                seen.discard(item_id)
                counts["skipped"] += 1
                continue
            if r.get("skipped"):
                # Listed but not to be taken in (refused by robots.txt, excluded by a rule): not seen, so an indexed
                # copy leaves search.
                seen.discard(item_id)
                counts["skipped"] += 1
                log.append(f"{r.get('title') or item_id}: {r['skipped']}")
                continue
            ex = state.held(item_id)
            if ex is not None and ex.marker == marker and ex.current:
                counts["unchanged"] += 1
            else:
                changed.append({**r, "marker": marker})
        if out.get("next_cursor") and out.get("next_cursor") == cursor:
            found.status = "partial"
            found.stopped = "The system named the same page again; the next run starts the listing again."
            errors.append({"phase": "list", "errorClass": "contract", "message": found.stopped})
            place.cursor = None
            await state.save(place)
            break
        cursor = out.get("next_cursor")
        # Saved after every page, so a run stopped by a limit or a restart resumes from here.
        place.cursor = cursor
        await state.save(place)
        if not cursor:
            found.watermark = str(out.get("watermark") or (_less_overlap(newest) if newest else since or ""))
            # The last page of a listing or of changes names where the next run's changes start.
            if out.get("cursor"):
                place.changes_cursor = out["cursor"]
            break

    if not found.resumes:
        seen |= carried
        place.seen_so_far = None
    found.pace = pace
    return found
