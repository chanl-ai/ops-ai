# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""A watched folder's check, by failure mode, on recorded SharePoint answers: a second page of changes is lost; a
file deleted at the source stays live; a stale place fetches every stored file again; two checks at once both run;
and a file too large to bring in is lost without a trace, or its held entry is removed."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ops_files.__main__ import RETENTION_CLASSES
from ops_files.service import FilesConfig
from ops_files.store import AsyncEngine, FilesStore, WatchesStore
from ops_files.tenant_files import TenantFiles
from ops_files.watches import WatchChecks
from ops_service_kit.http import JsonValue
from ops_sources import Answer
from ops_storage.local import LocalObjectStore
from ops_store import isolation

TEAM = "team_ap"
NOW = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
DECLARED: dict[str, JsonValue] = {
    "plugin": "sharepoint",
    "source": "files",
    "title": "SharePoint",
    "connectionId": "con_1",
    "connectionStatus": "healthy",
    "listTool": "sharepoint.list_files",
    "getTool": "sharepoint.get_file",
    "changesTool": "sharepoint.list_file_changes",
    "getTakesTag": True,
}


def _row(item: str, etag: str, **more: JsonValue) -> dict[str, JsonValue]:
    return {
        "id": f"drv!{item}",
        "title": f"{item}.pdf",
        "updated_at": "2026-11-24T08:00:00Z",
        "marker": etag,
        "folder": "Invoices",
        **more,
    }


def _file(item: str, etag: str, body: bytes) -> dict[str, JsonValue]:
    return {
        "id": f"drv!{item}",
        "title": f"{item}.pdf",
        "mime": "application/pdf",
        "folder": "Invoices",
        "encoding": "base64",
        "content": base64.b64encode(b"%PDF-1.7\n" + body).decode(),
        "marker": etag,
    }


class Recorded:
    """SharePoint as tools-service answers it: listing pages keyed by cursor, files by id, every call kept."""

    def __init__(self, pages: Any, got: dict[str, Any]) -> None:
        self.pages: dict[str | None, Any] = pages
        self.got = got
        self.calls: list[tuple[str | None, dict[str, JsonValue]]] = []
        self.hold: asyncio.Event | None = None

    async def declared(self, tenant_id: str, team_id: str) -> list[dict[str, JsonValue]]:
        return [DECLARED]

    async def call(
        self, tenant_id: str, team_id: str, tool: str | None, args: dict[str, JsonValue], *, act: str
    ) -> Answer:
        self.calls.append((tool, args))
        if self.hold is not None:
            await self.hold.wait()
        if tool == DECLARED["getTool"]:
            got = self.got[str(args["id"])]
            return got if isinstance(got, Answer) else Answer(True, got)
        cursor = args.get("cursor")
        if cursor not in self.pages:
            return Answer(False, code="INVALID_INPUT", message="The delta token expired (410).")
        return Answer(True, self.pages[cursor])

    def fetched(self) -> list[str]:
        return [str(a["id"]) for t, a in self.calls if t == DECLARED["getTool"]]


async def _setup(engine: AsyncEngine, tmp_path: Path, tenant: str, reader: Recorded) -> tuple[WatchChecks, str]:
    config = FilesConfig(retention_classes=RETENTION_CLASSES, default_retention_class="standard")
    files = TenantFiles(
        LocalObjectStore(tmp_path / "o", signing_key=b"k" * 32), FilesStore(engine), config, scanning="off"
    )
    watch_id = f"wat_{tenant}"
    with isolation.scope(tenant, TEAM):
        await WatchesStore(engine).create(
            {
                "tenant_id": tenant,
                "id": watch_id,
                "team": TEAM,
                "name": "Supplier invoices",
                "plugin": "sharepoint",
                "source": "files",
                "connection_id": "con_1",
                "values": {"libraries": ["drv"]},
                "created_by": "builder@harborpine.example",
                "created_at": NOW,
            },
            audit={"actor": "builder@harborpine.example", "action": "files.watch.created", "summary": "", "detail": {}},
        )
    return WatchChecks(files, reader, clock=lambda: NOW), watch_id


async def _entries(engine: AsyncEngine, tenant: str, watch_id: str) -> dict[str, tuple[int, bool]]:
    with isolation.scope(tenant, TEAM):
        held = await FilesStore(engine).held_sources(TEAM, watch_id)
        out: dict[str, tuple[int, bool]] = {}
        for source_id, h in held.items():
            row = await FilesStore(engine).get(h.file_id)
            assert row is not None
            out[source_id] = (row.file.version_count, h.removed)
    return out


async def test_both_pages_of_changes_arrive(engine: AsyncEngine, tmp_path: Path, tenant: str) -> None:
    reader = Recorded(
        {
            None: {"items": [_row("a", "e1")], "next_cursor": "p2"},
            "p2": {"items": [_row("b", "e1")], "next_cursor": None, "cursor": "delta-1"},
        },
        {"drv!a": _file("a", "e1", b"a"), "drv!b": _file("b", "e1", b"b")},
    )
    checks, watch_id = await _setup(engine, tmp_path, tenant, reader)
    with isolation.scope(tenant, TEAM):
        outcome = await checks.check(watch_id)
        events = await WatchesStore(engine).events(watch_id)
    assert (outcome.status, outcome.brought) == ("success", 2)
    assert [(e.number, e.kind) for e in events] == [(1, "new"), (2, "new")]
    assert set(await _entries(engine, tenant, watch_id)) == {"drv!a", "drv!b"}


async def test_a_file_deleted_at_the_source_is_marked_removed_and_kept(
    engine: AsyncEngine, tmp_path: Path, tenant: str
) -> None:
    first = {None: {"items": [_row("a", "e1"), _row("b", "e1")], "next_cursor": None}}
    reader = Recorded(first, {"drv!a": _file("a", "e1", b"a"), "drv!b": _file("b", "e1", b"b")})
    checks, watch_id = await _setup(engine, tmp_path, tenant, reader)
    with isolation.scope(tenant, TEAM):
        await checks.check(watch_id)
        reader.pages = {None: {"items": [_row("a", "e1"), {**_row("b", "e2"), "deleted": True}], "next_cursor": None}}
        outcome = await checks.check(watch_id)
        events = await WatchesStore(engine).events(watch_id, after=2)
    assert outcome.removed == 1 and [e.kind for e in events] == ["removed"]
    assert await _entries(engine, tenant, watch_id) == {"drv!a": (1, False), "drv!b": (1, True)}


async def test_a_stale_place_lists_again_and_fetches_no_stored_version(
    engine: AsyncEngine, tmp_path: Path, tenant: str
) -> None:
    reader = Recorded(
        {
            None: {"items": [_row("a", "e1")], "next_cursor": "p2"},
            "p2": {"items": [_row("b", "e1")], "next_cursor": None},
        },
        {"drv!a": _file("a", "e1", b"a"), "drv!b": _file("b", "e1", b"b")},
    )
    checks, watch_id = await _setup(engine, tmp_path, tenant, reader)
    with isolation.scope(tenant, TEAM):
        await checks.check(watch_id)
        # A check stopped part way saved a page that SharePoint has since dropped (410): the library is listed again.
        watches = WatchesStore(engine)
        row = await watches.get(watch_id)
        assert row is not None
        await watches.claim(watch_id, owner="seed", seconds=1)
        await watches.save_place(watch_id, owner="seed", place={**row.place, "cursor": "gone"})
        await watches.finish(watch_id, owner="seed", outcome={}, at=NOW)
        reader.pages = {None: {"items": [_row("a", "e1"), _row("b", "e1")], "next_cursor": None}}
        reader.calls.clear()
        outcome = await checks.check(watch_id)
    assert outcome.status == "success"
    assert reader.fetched() == []
    assert [a.get("cursor") for _, a in reader.calls] == ["gone", None]


async def test_two_checks_at_once_run_one_and_the_changed_file_is_version_two(
    engine: AsyncEngine, tmp_path: Path, tenant: str
) -> None:
    reader = Recorded({None: {"items": [_row("a", "e1")], "next_cursor": None}}, {"drv!a": _file("a", "e1", b"a")})
    checks, watch_id = await _setup(engine, tmp_path, tenant, reader)
    with isolation.scope(tenant, TEAM):
        await checks.check(watch_id)
        reader.pages = {None: {"items": [_row("a", "e2")], "next_cursor": None}}
        reader.got = {"drv!a": _file("a", "e2", b"a, paid")}
        reader.hold = asyncio.Event()
        running = asyncio.create_task(checks.check(watch_id))
        await asyncio.sleep(0.2)
        other = asyncio.create_task(checks.check(watch_id))
        await asyncio.sleep(0.2)
        reader.hold.set()
        first, second = await running, await other
    assert (first.status, second.status) == ("success", "already_checking")
    assert await _entries(engine, tenant, watch_id) == {"drv!a": (2, False)}


async def test_a_file_too_large_is_one_failed_event_and_its_entry_stays(
    engine: AsyncEngine, tmp_path: Path, tenant: str
) -> None:
    reader = Recorded(
        {None: {"items": [_row("a", "e1"), _row("b", "e1")], "next_cursor": None}},
        {"drv!a": _file("a", "e1", b"a"), "drv!b": _file("b", "e1", b"b")},
    )
    checks, watch_id = await _setup(engine, tmp_path, tenant, reader)
    with isolation.scope(tenant, TEAM):
        await checks.check(watch_id)
        # b grew past what the listing takes in; c is new and refused at fetch for its size.
        reader.pages = {
            None: {
                "items": [
                    _row("a", "e1"),
                    _row("b", "e2", skipped="Larger than 25 MB", size=31457280),
                    _row("c", "e1", size=19922944),
                ],
                "next_cursor": None,
            }
        }
        reader.got["drv!c"] = Answer(False, code="RESPONSE_TOO_LARGE", message="The answer is over 25 MB.")
        outcome = await checks.check(watch_id)
        events = await WatchesStore(engine).events(watch_id, after=2)
    assert (outcome.failed, outcome.removed) == (2, 0)
    assert sorted((e.kind, e.path, e.size) for e in events) == [
        ("failed", "b.pdf", 31457280),
        ("failed", "c.pdf", 19922944),
    ]
    assert await _entries(engine, tenant, watch_id) == {"drv!a": (1, False), "drv!b": (1, False)}
