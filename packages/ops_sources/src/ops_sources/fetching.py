# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Fetch a version: the changed items, a few at once and paced, each sent its held version tag.

An item the listing already read (a crawl following links) is kept as listed, not fetched again. An item the system
answers gone (404 or 410) is counted, and removed only on the second run in a row that finds it gone, then
tombstoned: one miss may be the site's hiccup. A rate limit on a fetch ends the run partial."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import cast

from ops_service_kit.http import Json, JsonValue
from ops_service_kit.narrow import an_object

from .contract import Answer, SourceError, SourceTools
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
    ) -> Fetched:
        """Every changed item of the listing: those it carried whole go to `on_listed` first, then the rest are
        fetched at once and each new version goes to `on_fetched`, in listing order. The first fetch that raises
        fails the run. Counts `unchanged` and `failed` into `counts`."""
        done = Fetched()
        listed_whole = [r for r in self.listing.changed if "content" in r]
        changed = [r for r in self.listing.changed if "content" not in r]
        for r in listed_whole:
            await on_listed(r, r)
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
                continue
            item = an_object(got.output, "fetched item")
            if item.get("unchanged") is True:
                if self.state.held(item_id) is not None:
                    await self.state.mark(item_id, str(r["marker"]))
                counts["unchanged"] += 1
                continue
            await on_fetched(r, item)
        return done
