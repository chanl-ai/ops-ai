# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Test support, never used by a service: a Graph delta source over a list of messages, and one over a folder of JSON
files. Both serve Graph-shaped items and parse them as Graph does. A dev stack reads real mailboxes on GreenMail."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .graph import GraphParse
from .inbound import DeltaPage


class FakeMailSource(GraphParse):
    """Serves `items` in pages. A deltaLink `delta:<n>` means "everything after the first n items"; a nextLink
    `page:<start>:<end>` names the slice still to serve in this sync. `fail_once_at` raises on the first request for
    that page start, as a connection lost mid-poll."""

    def __init__(self, items: list[dict[str, Any]], *, page_size: int = 20, fail_once_at: int | None = None) -> None:
        self.items = list(items)
        self.page_size = page_size
        self.fail_once_at = fail_once_at
        self.requests = 0

    async def cursor_now(self) -> str:
        return f"delta:{len(self.items)}"

    def arrive(self, *items: dict[str, Any]) -> None:
        self.items.extend(items)

    async def delta(self, link: str | None) -> DeltaPage:
        self.requests += 1
        if link is None or link.startswith("delta:"):
            start, end = (0 if link is None else int(link.split(":")[1])), len(self.items)
        else:
            _, s, e = link.split(":")
            start, end = int(s), int(e)
        if self.fail_once_at is not None and start == self.fail_once_at:
            self.fail_once_at = None
            raise ConnectionError(f"connection lost at item {start}")
        stop = min(start + self.page_size, end)
        page = self.items[start:stop]
        if stop < end:
            return DeltaPage(page, f"page:{stop}:{end}", None)
        return DeltaPage(page, None, f"delta:{end}")


class FileMailSource(FakeMailSource):
    """The fake source a dev stack polls: every `*.json` directly under `folder`, in the order dropped (modification
    time, then name), is one Graph delta item or a list of them. Drop order keeps the delta cursor, a count of items
    served, pointing past what was served: a later file sorting earlier by name would shift it. The folder is re-read
    on each request, so a script that writes a file has "sent" a message. A file named by the message key overwrites
    itself on a second drop, and the consumer's dedupe makes the replay a no-op anyway."""

    def __init__(self, folder: Path, *, page_size: int = 20) -> None:
        super().__init__([], page_size=page_size)
        self.folder = folder

    def reload(self) -> None:
        items: list[dict[str, Any]] = []
        paths = list(self.folder.glob("*.json")) if self.folder.is_dir() else []
        for path in sorted(paths, key=lambda f: (f.stat().st_mtime_ns, f.name)):
            loaded: Any = json.loads(path.read_text())
            found: list[dict[str, Any]] = list(loaded) if isinstance(loaded, list) else [loaded]  # pyright: ignore[reportUnknownArgumentType]
            items.extend(found)
        self.items = items

    async def delta(self, link: str | None) -> DeltaPage:
        self.reload()
        return await super().delta(link)

    async def cursor_now(self) -> str:
        self.reload()
        return await super().cursor_now()


def fake_folder(root: Path, mailbox: str, folder: str) -> Path:
    """Where the dev fake keeps a mailbox folder: the mailbox's own directory is its inbox, and a subdirectory named
    for another folder holds that folder's mail."""
    return root / mailbox if folder.lower() == "inbox" else root / mailbox / folder
