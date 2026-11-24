# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Fetch a version: the changed items, a few at once and paced, each sent its held version tag.

An item the listing already read (a crawl following links) is kept as listed, not fetched again. An item the system
answers gone (404 or 410) is counted, and removed only on the second run in a row that finds it gone, then
tombstoned: one miss may be the site's hiccup. A rate limit on a fetch ends the run partial. Any other failed fetch is
kept in the place for the version it failed on: said once per version (`failed_first`), and tried again
(`retrying`, so the reading service ends the run partial and lists it again) until FETCH_TRIES runs have; then the
listing leaves it until its marker moves."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from typing import cast

from ops_service_kit.http import Json, JsonValue
from ops_service_kit.narrow import an_object, json_object

from .contract import FETCH_TRIES, PASSING, Answer, SourceError, SourceTools
from .listing import Listing
from .state import Place, Reader, SourceState

# Runs in a row an item must answer gone (404 or 410) before it is removed: one miss may be the site's hiccup.
GONE_TWICE = 2

# What the reading service does with one item: the listed row (its marker set) and the item as fetched or listed.
OnItem = Callable[[Json, Json], Awaitable[None]]


class Pacer:
    """One turn every `pace` seconds, shared by a run's fetches whatever their concurrency."""

    def __init__(self, pace: float) -> None:
        self.pace = pace
        self.next = 0.0
        self.lock = asyncio.Lock()

    async def turn(self) -> None:
        if self.pace <= 0:
            return
        async with self.lock:
            now = time.monotonic()
            if self.next > now:
                await asyncio.sleep(self.next - now)
            self.next = max(now, self.next) + self.pace


@dataclass
class Fetched:
    """What the fetch of a run's changed items settled beyond what it handed on."""

    # Ids that answered gone for the second run in a row, now tombstoned in the place.
    gone_now: list[str] = field(default_factory=list[str])
    # A fetch hit the system's rate limit, so the run is partial.
    rate_limited: bool = False
    # Ids whose fetch failed for the first time on their current version: each is said once, as one failure.
    failed_first: list[str] = field(default_factory=list[str])
    # Ids whose fetch failed and are tried again on the next run, so the run must not settle as a success.
    retrying: list[str] = field(default_factory=list[str])


class Fetcher:
    """A run's fetches of one source: at most `tools.fetch_at_once` at a time, one turn of the pace each."""

    def __init__(
        self,
        reader: Reader,
        state: SourceState,
        tools: SourceTools,
        listing: Listing,
        *,
        tenant: str,
        team: str,
        act: str,
    ) -> None:
        self.reader, self.state, self.tools, self.listing = reader, state, tools, listing
        self.tenant, self.team, self.act = tenant, team, act
        self.lock = asyncio.Semaphore(tools.fetch_at_once)
        self.paced = Pacer(listing.pace)

    async def fetch(self, item_id: str) -> Answer:
        """One item, sent the version tag held for it so the system can answer `unchanged` without sending it."""
        held = self.state.held(item_id)
        tag: dict[str, JsonValue] = {"tag": held.tag} if self.tools.get_takes_tag and held and held.tag else {}
        async with self.lock:
            await self.paced.turn()
            if self.tools.get is None:
                raise KeyError("getTool")
            args: dict[str, JsonValue] = {**self.listing.given, "id": item_id, **tag}
            return await self.reader.call(self.tenant, self.team, self.tools.get, args, act=self.act)

    async def fetch_changed(
        self,
        place: Place,
        counts: dict[str, int],
        errors: list[SourceError],
        log: list[str],
        *,
        on_listed: OnItem,
        on_fetched: OnItem,
        final: Collection[str] = (),
    ) -> Fetched:
        """Every changed item of the listing: those it carried whole go to `on_listed` first, then the rest are
        fetched at once and each new version goes to `on_fetched`, in listing order. The first fetch that raises
        fails the run. A failure whose code is in `final` (too large to carry) is left at once, not tried again.
        Counts `unchanged` and `failed` into `counts`."""
        done = Fetched()
        listed_whole = [r for r in self.listing.changed if "content" in r]
        changed = [r for r in self.listing.changed if "content" not in r]
        for r in listed_whole:
            await on_listed(r, r)
            place.failed_fetches.pop(str(r["id"]), None)
        try:
            async with asyncio.TaskGroup() as group:
                fetches = [group.create_task(self.fetch(str(r["id"]))) for r in changed]
        except ExceptionGroup as failed:
            # The run fails on the first fetch that raised, as one fetch at a time would.
            raise failed.exceptions[0] from None
        answers = [f.result() for f in fetches]
        for r, got in zip(changed, answers, strict=True):
            item_id = str(r["id"])
            if not got.ok and got.code == "NOT_FOUND" and (held := self.state.held(item_id)) is not None:
                # Gone at the source: removed on the second run in a row that finds it gone, then tombstoned.
                place.failed_fetches.pop(item_id, None)
                count = held.gone_count + 1
                await self.state.gone(item_id, count)
                if count >= GONE_TWICE:
                    done.gone_now.append(item_id)
                    place.tombstones[item_id] = {
                        "at": self.listing.started.isoformat(),
                        "reason": got.message or "Gone at the source",
                    }
                else:
                    log.append(f"{held.title}: answered gone once; removed if it answers so again")
                continue
            if not got.ok:
                counts["failed"] += 1
                errors.append(
                    {
                        "itemTitle": cast(str | None, r.get("title")),
                        "phase": "get",
                        "errorClass": got.code,
                        "message": got.message,
                    }
                )
                if got.code == "RATE_LIMITED":
                    done.rate_limited = True
                if got.code not in PASSING:
                    self._failed(place, done, r, got, final=got.code in final)
                continue
            place.failed_fetches.pop(item_id, None)
            item = an_object(got.output, "fetched item")
            if item.get("unchanged") is True:
                if self.state.held(item_id) is not None:
                    await self.state.mark(item_id, str(r["marker"]))
                counts["unchanged"] += 1
                continue
            await on_fetched(r, item)
        return done

    def _failed(self, place: Place, done: Fetched, r: Json, got: Answer, *, final: bool) -> None:
        """Keeps a failed fetch in the place for the version it failed on, counting the runs in a row that tried it."""
        item_id, marker = str(r["id"]), str(r["marker"])
        before = json_object(place.failed_fetches.get(item_id))
        same = before.get("marker") == marker
        tried = before.get("tries") if same else 0
        tries = FETCH_TRIES if final else (tried if isinstance(tried, int) else 0) + 1
        place.failed_fetches[item_id] = {
            "marker": marker,
            "tries": tries,
            "at": self.listing.started.isoformat(),
            "reason": (got.message or got.code)[:300],
        }
        if not same:
            done.failed_first.append(item_id)
        if tries < FETCH_TRIES:
            done.retrying.append(item_id)
