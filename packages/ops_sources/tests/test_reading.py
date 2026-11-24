"""The shared reading loop with a caller's own state, the way a service other than knowledge holds it: every page of
changes read with the place saved after each page, only items whose marker moved fetched, and the place moved on to
the watermark once the listing finishes. kb-service's sync suite guards the knowledge state."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from ops_service_kit.http import Json, JsonValue
from ops_sources import Answer, Fetcher, Held, Listing, Place, SourceTools, access_list, read_changes

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


async def _list(folder: Folder, watch: Watch, tools: SourceTools, values: JsonValue) -> tuple[Listing, Place]:
    place = Place()
    counts = {"listed": 0, "unchanged": 0, "skipped": 0, "failed": 0}
    listing = await read_changes(
        folder, watch, place, tools, tenant="local", team="team_ap", values=values, connection_id="con_ap",
        full=True, trigger="schedule", act="files-check:watch_1", counts=counts,
        clock=lambda: datetime(2026, 11, 22, tzinfo=UTC),
    )  # fmt: skip
    return listing, place


def test_an_access_list_keeps_not_said_apart_from_nobody() -> None:
    assert access_list({"id": "plan.xlsx"}) is None
    assert access_list({"id": "plan.xlsx", "allowed": []}) == []
    assert access_list({"id": "plan.xlsx", "allowed": ["grp_finance"]}) == ["grp_finance"]


async def test_a_file_too_large_to_take_in_is_handed_back_with_its_reason() -> None:
    folder = Folder()
    big: JsonValue = {
        "items": [{"id": "scan.tif", "updated_at": "2026-11-20T09:00:00Z", "size": 31_000_000, "skipped": "over 25 MB"}]
    }

    async def call(tenant_id: str, team_id: str, tool: str | None, args: dict[str, JsonValue], *, act: str) -> Answer:
        return Answer(True, big)

    folder.call = call  # type: ignore[method-assign]
    listing, _ = await _list(folder, Watch({}), SourceTools(list="list_files", get="get_file"), None)
    assert [(r["id"], r["skipped"], r["size"]) for r in listing.skipped] == [("scan.tif", "over 25 MB", 31_000_000)]
    assert listing.changed == [] and "scan.tif" not in listing.seen


async def test_fetches_wait_out_the_source_rate_and_its_limit_at_once() -> None:
    folder = Folder()
    running, most = 0, 0
    real = folder.call

    async def call(tenant_id: str, team_id: str, tool: str | None, args: dict[str, JsonValue], *, act: str) -> Answer:
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.01 if tool == "get_file" else 0)
        running -= 1
        return await real(tenant_id, team_id, tool, args, act=act)

    folder.call = call  # type: ignore[method-assign]

    async def fetch_all(tools: SourceTools, values: JsonValue) -> float:
        watch = Watch({})
        listing, place = await _list(folder, watch, tools, values)
        began = time.monotonic()
        fetcher = Fetcher(folder, watch, tools, listing, tenant="local", team="team_ap", act="files-check:watch_1")
        await fetcher.fetch_changed(place, {"unchanged": 0, "failed": 0}, [], [], on_listed=_none, on_fetched=_none)
        return time.monotonic() - began

    # Twenty a second: three fetches a turn of 0.05 s apart, so the third starts no sooner than 0.1 s in.
    assert await fetch_all(SourceTools(list="list_files", get="get_file"), {"rate": 20}) >= 0.1
    # One at once, unpaced: no two fetches overlap.
    most = 0
    await fetch_all(SourceTools(list="list_files", get="get_file", fetch_at_once=1), None)
    assert most == 1


async def test_a_file_the_source_answers_unchanged_keeps_its_new_marker() -> None:
    folder = Folder()
    marked: list[tuple[str, str]] = []

    async def call(tenant_id: str, team_id: str, tool: str | None, args: dict[str, JsonValue], *, act: str) -> Answer:
        if tool == "get_file":
            return Answer(True, {"unchanged": True})
        return Answer(True, PAGES[str(args["cursor"]) if "cursor" in args else None])

    folder.call = call  # type: ignore[method-assign]
    watch = Watch({"inv-001.pdf": Held(marker="e0", tag="t0", current=True, gone_count=0, title="inv-001.pdf")})

    async def mark(item_id: str, marker: str) -> None:
        marked.append((item_id, marker))

    watch.mark = mark  # type: ignore[method-assign]
    tools = SourceTools(list="list_files", get="get_file", get_takes_tag=True)
    listing, place = await _list(folder, watch, tools, None)
    fetcher = Fetcher(folder, watch, tools, listing, tenant="local", team="team_ap", act="files-check:watch_1")
    await fetcher.fetch_changed(place, {"unchanged": 0, "failed": 0}, [], [], on_listed=_none, on_fetched=_none)
    assert marked == [("inv-001.pdf", "e1")]


async def _none(row: Json, item: Json) -> None: ...
