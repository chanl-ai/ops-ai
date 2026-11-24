# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Reading a source through its connection's tools, shared by every service that does: knowledge today, Files next.

The loop lists what changed since the saved place with every page read, compares markers with what the reading
service holds, and fetches the changed items a few at once and paced. The reading service keeps the place and its
items behind the state port (`SourceState`) and decides what a fetched item becomes. The roles a source answers are
in `ops_sources.contract`."""

from .contract import (
    AT_ONCE,
    RECONNECT,
    Answer,
    FoundPlace,
    SourceError,
    SourceTools,
    access_list,
    listing_of,
    places_of,
)
from .fetching import GONE_TWICE, Fetched, Fetcher, OnItem, Pacer
from .listing import FULL_EVERY, MAX_PAGES, OVERLAP, STALE_CURSOR, Listing, read_changes
from .reader import ToolReader
from .state import Held, Place, Reader, SourceState

__all__ = [
    "AT_ONCE",
    "FULL_EVERY",
    "GONE_TWICE",
    "MAX_PAGES",
    "OVERLAP",
    "RECONNECT",
    "STALE_CURSOR",
    "Answer",
    "Fetched",
    "Fetcher",
    "FoundPlace",
    "Held",
    "Listing",
    "OnItem",
    "Pacer",
    "Place",
    "Reader",
    "SourceError",
    "SourceState",
    "SourceTools",
    "ToolReader",
    "access_list",
    "listing_of",
    "places_of",
    "read_changes",
]
