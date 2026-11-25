# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The state port: what a reading service keeps for one source between runs, and what it holds for each item.

The loop owns no table. The service that reads a source keeps its place (where the listing got to, the watermark,
the changes cursor, the last full listing, the tombstones) wherever it keeps the source, and answers for each item
what it holds (its marker and version tag, whether it is settled, how many runs in a row found it gone). Knowledge
keeps these in the knowledge source's config and its items; Files keeps them on its watch and its source files."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ops_service_kit.http import Json, JsonValue

from .contract import Answer


@dataclass
class Place:
    """Where a source's reading got to, saved after every page so a stopped run resumes from it."""

    # The next page of a listing in progress; None when the last listing finished.
    cursor: JsonValue = None
    # Where the next run's listing starts: the system's watermark, or the newest change seen less an overlap.
    watermark: JsonValue = None
    # The changes tool's own cursor, named on the last page of a listing or of changes.
    changes_cursor: JsonValue = None
    # ISO time of the last listing read from its first page to its last.
    last_full_at: str | None = None
    # What a listing longer than one run has listed so far; None when no such listing is in progress.
    seen_so_far: list[str] | None = None
    # Items removed after answering gone twice, by id, each with when and why; not taken in again until lifted.
    tombstones: Json = field(default_factory=dict[str, JsonValue])
    # `needs_reconnect` while the connection refuses its sign-in.
    paused: bool | str | None = None


@dataclass(frozen=True)
class Held:
    """What the reading service holds for one item of the source."""

    marker: str | None
    # The version tag the get tool is sent, so the system can answer `unchanged`.
    tag: str | None
    # The held copy is settled (read and kept), so a matching marker means nothing to fetch.
    current: bool
    gone_count: int
    title: str


class SourceState(Protocol):
    """The reading service's side of one source: its held items and where to save the place."""

    def held(self, item_id: str) -> Held | None:
        """What is held for the item now; an item written earlier in the same run answers as written."""
        ...

    async def save(self, place: Place) -> None:
        """Keep the place, so the next run (or a restarted one) reads from it."""
        ...

    async def mark(self, item_id: str, marker: str) -> None:
        """The system answered `unchanged` for a held item: keep its new marker."""
        ...

    async def gone(self, item_id: str, count: int) -> None:
        """A held item answered gone `count` runs in a row."""
        ...


class Reader(Protocol):
    """How the loop reaches the source's tools (`ops_sources.ToolReader` in a service, a fake in tests)."""

    async def declared(self, tenant_id: str, team_id: str) -> list[dict[str, JsonValue]]: ...

    async def call(
        self, tenant_id: str, team_id: str, tool: str | None, args: dict[str, JsonValue], *, act: str
    ) -> Answer: ...
