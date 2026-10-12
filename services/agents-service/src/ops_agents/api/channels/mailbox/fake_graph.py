"""A fake Graph delta source over a list of messages, for tests and the E6 measurements."""

from __future__ import annotations

from typing import Any

from .graph_port import DeltaPage


class FakeMailSource:
    """Serves `items` in pages. A deltaLink `delta:<n>` means "everything after the first n items"; a nextLink
    `page:<start>:<end>` names the slice still to serve in this sync. `fail_once_at` raises on the first request for
    that page start, as a connection lost mid-poll."""

    def __init__(self, items: list[dict[str, Any]], *, page_size: int = 20, fail_once_at: int | None = None) -> None:
        self.items = list(items)
        self.page_size = page_size
        self.fail_once_at = fail_once_at
        self.requests = 0

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
