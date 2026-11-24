"""The shared reading loop with a caller's own state, the way a service other than knowledge holds it: every page of
changes read with the place saved after each page, only items whose marker moved fetched, and the place moved on to
the watermark once the listing finishes. kb-service's sync suite guards the knowledge state."""

from __future__ import annotations

from datetime import UTC, datetime

from ops_service_kit.http import Json, JsonValue
from ops_sources import Answer, Fetcher, Held, Place, SourceTools, read_changes

PAGES: dict[str | None, JsonValue] = {
    None: {
        "items": [
            {"id": "inv-001.pdf", "updated_at": "2026-11-20T09:00:00Z", "marker": "e1"},
            {"id": "inv-002.pdf", "updated_at": "2026-11-20T09:05:00Z", "marker": "e2"},
        ],
        "next_cursor": "2",
    },
    "2": {
        "items": [{"id": "inv-003.pdf", "updated_at": "2026-11-21T10:00:00Z", "marker": "e3"}],
        "watermark": "2026-11-21T10:00:00Z",
        "cursor": "delta-7",
    },
}


class Folder:
    """A folder of invoices as its tools answer: two pages of listing, and each file by id."""

    def __init__(self) -> None:
        self.calls: list[tuple[str | None, dict[str, JsonValue]]] = []

    async def declared(self, tenant_id: str, team_id: str) -> list[dict[str, JsonValue]]:
        return []

    async def call(
        self, tenant_id: str, team_id: str, tool: str | None, args: dict[str, JsonValue], *, act: str
    ) -> Answer:
        self.calls.append((tool, args))
        if tool == "list_files":
            return Answer(True, PAGES[str(args["cursor"]) if "cursor" in args else None])
        return Answer(True, {"id": args["id"], "content": "invoice", "mime": "application/pdf"})


class Watch:
    """A watch's state: the files it holds and every place it saved."""

    def __init__(self, held: dict[str, Held]) -> None:
        self.files = held
        self.saved: list[JsonValue] = []

    def held(self, item_id: str) -> Held | None:
        return self.files.get(item_id)

    async def save(self, place: Place) -> None:
        self.saved.append(place.cursor)

    async def mark(self, item_id: str, marker: str) -> None: ...

    async def gone(self, item_id: str, count: int) -> None: ...


async def test_every_page_is_read_with_its_place_saved_and_only_moved_files_fetched() -> None:
    folder = Folder()
    watch = Watch({"inv-002.pdf": Held(marker="e2", tag="e2", current=True, gone_count=0, title="inv-002.pdf")})
    place = Place()
    tools = SourceTools(list="list_files", get="get_file", changes="list_changes")
    counts = {"listed": 0, "unchanged": 0, "skipped": 0, "failed": 0}
    listing = await read_changes(
        folder, watch, place, tools, tenant="local", team="team_ap", values={"folder": "Invoices"},
        connection_id="con_ap", full=False, trigger="schedule", act="files-check:watch_1", counts=counts,
        clock=lambda: datetime(2026, 11, 22, tzinfo=UTC),
    )  # fmt: skip
    assert watch.saved == ["2", None], watch.saved
    assert [r["id"] for r in listing.changed] == ["inv-001.pdf", "inv-003.pdf"]
    assert counts == {"listed": 3, "unchanged": 1, "skipped": 0, "failed": 0}

    kept: list[str] = []

    async def keep(row: Json, item: Json) -> None:
        kept.append(str(item["id"]))

    fetcher = Fetcher(folder, watch, tools, listing, tenant="local", team="team_ap", act="files-check:watch_1")
    await fetcher.fetch_changed(place, counts, listing.errors, listing.log, on_listed=keep, on_fetched=keep)
    assert kept == ["inv-001.pdf", "inv-003.pdf"]
    assert all(args.get("source") == {"folder": "Invoices"} for _, args in folder.calls)

    listing.settle(place, "success")
    assert (place.watermark, place.changes_cursor, place.cursor) == ("2026-11-21T10:00:00Z", "delta-7", None)
    assert place.last_full_at == "2026-11-22T00:00:00+00:00"
