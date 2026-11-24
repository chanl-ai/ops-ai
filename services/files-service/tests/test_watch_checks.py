# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""A watched folder's check, by failure mode, on recorded SharePoint answers: a second page of changes is lost, or a
check that dies part way loses the events of the versions it wrote; a file deleted or moved at the source stays live,
or a listing of changes removes the files it did not list; a stale place fetches every stored file again or misses a
delete; two checks at once both run, or one that lost its lease writes on; a file too large to bring in is lost
without a trace or its held entry removed, and one a rule leaves out is called failed; a fetch that failed for a
passing reason is dropped while the check says success; and a refused sign-in raises instead of saying why, ending
the pass for every other watch."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from ops_files.__main__ import RETENTION_CLASSES
from ops_files.service import FilesConfig
from ops_files.store import AsyncEngine, FilesStore, WatchesStore
from ops_files.store.watches import file_watches
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
    """SharePoint as tools-service answers it: a full listing's pages keyed by cursor, and changes (a `since` listing
    or the changes tool) keyed by cursor in `changes`, which lists only what changed; files by id, every call kept. A
    fetch answer that is an exception is raised, as a process that dies part way does."""

    def __init__(self, pages: Any, got: dict[str, Any]) -> None:
        self.pages: dict[str | None, Any] = pages
        self.changes: dict[str | None, Any] = {None: {"items": [], "next_cursor": None}}
        self.got = got
        self.rows: list[dict[str, JsonValue]] = [dict(DECLARED)]
        self.calls: list[tuple[str | None, dict[str, JsonValue]]] = []
        self.hold: asyncio.Event | None = None
        self.on_get: Any = None

    async def declared(self, tenant_id: str, team_id: str) -> list[dict[str, JsonValue]]:
        return self.rows

    async def call(
        self, tenant_id: str, team_id: str, tool: str | None, args: dict[str, JsonValue], *, act: str
    ) -> Answer:
        self.calls.append((tool, args))
        if self.hold is not None:
            await self.hold.wait()
        if tool == DECLARED["getTool"]:
            if self.on_get is not None:
                await self.on_get(str(args["id"]))
            got = self.got[str(args["id"])]
            if isinstance(got, BaseException):
                raise got
            return got if isinstance(got, Answer) else Answer(True, got)
        answers = self.changes if tool == DECLARED["changesTool"] or "since" in args else self.pages
        cursor = args.get("cursor")
        if isinstance(answers, Answer):
            return answers
        if cursor not in answers:
            return Answer(False, code="INVALID_INPUT", message="The delta token expired (410).")
        return answers[cursor] if isinstance(answers[cursor], Answer) else Answer(True, answers[cursor])

    def fetched(self) -> list[str]:
        return [str(a["id"]) for t, a in self.calls if t == DECLARED["getTool"]]


async def _setup(
    engine: AsyncEngine, tmp_path: Path, tenant: str, reader: Recorded, watch_id: str = ""
) -> tuple[WatchChecks, str]:
    config = FilesConfig(retention_classes=RETENTION_CLASSES, default_retention_class="standard")
    files = TenantFiles(
        LocalObjectStore(tmp_path / "o", signing_key=b"k" * 32), FilesStore(engine), config, scanning="off"
    )
    watch_id = watch_id or f"wat_{tenant}"
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
                "values": {"libraries": ["drv", "drv2"]},
                "created_by": "builder@harborpine.example",
                "created_at": NOW,
            },
            audit={"actor": "builder@harborpine.example", "action": "files.watch.created", "summary": "", "detail": {}},
        )
    return WatchChecks(files, reader, clock=lambda: clock[0]), watch_id


# The checks' clock, moved on by a test that needs the next check to list whole (a week after the last full one).
clock = [NOW]


@pytest.fixture(autouse=True)
def _clock() -> None:
    clock[0] = NOW


async def _entries(engine: AsyncEngine, tenant: str, watch_id: str) -> dict[str, tuple[int, bool]]:
    with isolation.scope(tenant, TEAM):
        held = await FilesStore(engine).held_sources(TEAM, watch_id)
        out: dict[str, tuple[int, bool]] = {}
        for source_id, h in held.items():
            row = await FilesStore(engine).get(h.file_id)
            assert row is not None
            out[source_id] = (row.file.version_count, h.removed)
    return out


async def test_both_pages_arrive_and_a_check_that_dies_keeps_its_versions_events(
    engine: AsyncEngine, tmp_path: Path, tenant: str
) -> None:
    files: dict[str, Any] = {f"drv!{i}": _file(i, "e1", i.encode()) for i in "abcde"}
    # e is fetched in the second group of four; the process dies on it, after a to d are written.
    files["drv!e"] = RuntimeError("the process died")
    reader = Recorded(
        {
            None: {"items": [_row(i, "e1") for i in "abc"], "next_cursor": "p2"},
            "p2": {"items": [_row(i, "e1") for i in "de"], "next_cursor": None, "cursor": "delta-1"},
        },
        files,
    )
    checks, watch_id = await _setup(engine, tmp_path, tenant, reader)
    with isolation.scope(tenant, TEAM):
        with pytest.raises(RuntimeError):
            await checks.check(watch_id)
        events = await WatchesStore(engine).events(watch_id)
        assert [(e.number, e.kind, e.path) for e in events] == [
            (n + 1, "new", f"Invoices/{i}.pdf") for n, i in enumerate("abcd")
        ]
        reader.got["drv!e"] = _file("e", "e1", b"e")
        outcome = await checks.check(watch_id)
        events = await WatchesStore(engine).events(watch_id, after=4)
    assert (outcome.status, outcome.brought) == ("success", 1)
    assert [(e.number, e.kind) for e in events] == [(5, "new")]
    assert set(await _entries(engine, tenant, watch_id)) == {f"drv!{i}" for i in "abcde"}
    with isolation.scope(tenant, TEAM):
        row = await FilesStore(engine).get(str(events[0].file_id))
    # The listing's modified time is the version's change at the source, which the file page shows.
    assert row is not None and row.versions[0].source_changed_at == datetime(2026, 11, 24, 8, 0, tzinfo=UTC)


async def test_a_file_deleted_or_moved_at_the_source_is_marked_removed_and_kept(
    engine: AsyncEngine, tmp_path: Path, tenant: str
) -> None:
    first = {None: {"items": [_row("a", "e1"), _row("b", "e1")], "next_cursor": None}}
    reader = Recorded(first, {"drv!a": _file("a", "e1", b"a"), "drv!b": _file("b", "e1", b"b")})
    checks, watch_id = await _setup(engine, tmp_path, tenant, reader)
    with isolation.scope(tenant, TEAM):
        await checks.check(watch_id)
        # The changes since: b moved to the second library, which SharePoint lists as a delete in one and a new id in
        # the other. a is unchanged, so the listing of changes does not name it.
        moved = {**_row("b", "e1"), "id": "drv2!b"}
        reader.changes = {None: {"items": [{**_row("b", "e2"), "deleted": True}, moved], "next_cursor": None}}
        reader.got["drv2!b"] = {**_file("b", "e1", b"b"), "id": "drv2!b"}
        outcome = await checks.check(watch_id)
        events = await WatchesStore(engine).events(watch_id, after=2)
    assert (outcome.removed, outcome.brought) == (1, 1)
    assert sorted(e.kind for e in events) == ["new", "removed"]
    assert await _entries(engine, tenant, watch_id) == {"drv!a": (1, False), "drv!b": (1, True), "drv2!b": (1, False)}


async def test_a_stale_place_lists_again_fetches_no_stored_version_and_finds_a_delete(
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
        # A check stopped part way saved a page that SharePoint has since dropped (410): the changes are listed again.
        watches = WatchesStore(engine)
        row = await watches.get(watch_id)
        assert row is not None
        await watches.claim(watch_id, owner="seed", seconds=1)
        await watches.save_place(watch_id, owner="seed", place={**row.place, "cursor": "gone"}, seconds=1)
        await watches.finish(watch_id, owner="seed", outcome={}, at=NOW)
        reader.changes = {None: {"items": [_row("a", "e1"), {**_row("b", "e2"), "deleted": True}], "next_cursor": None}}
        reader.calls.clear()
        outcome = await checks.check(watch_id)
    assert (outcome.status, outcome.removed) == ("success", 1)
    assert reader.fetched() == []
    assert [a.get("cursor") for _, a in reader.calls] == ["gone", None]
    assert await _entries(engine, tenant, watch_id) == {"drv!a": (1, False), "drv!b": (1, True)}


async def test_two_checks_at_once_run_one_and_a_check_that_lost_its_lease_stops(
    engine: AsyncEngine, tmp_path: Path, tenant: str
) -> None:
    reader = Recorded({None: {"items": [_row("a", "e1")], "next_cursor": None}}, {"drv!a": _file("a", "e1", b"a")})
    checks, watch_id = await _setup(engine, tmp_path, tenant, reader)
    with isolation.scope(tenant, TEAM):
        await checks.check(watch_id)
        reader.changes = {None: {"items": [_row("a", "e2")], "next_cursor": None}}
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
        # The next check's lease runs out while b is fetched and another check takes the watch: this one writes
        # nothing more, so two checks never write one watch.
        reader.hold = None
        reader.changes = {None: {"items": [_row("a", "e3"), _row("b", "e1")], "next_cursor": None}}
        reader.got = {"drv!a": _file("a", "e3", b"a, refunded"), "drv!b": _file("b", "e1", b"b")}

        async def taken(_item: str) -> None:
            # In the tenant's own transaction: SQL Server's row security hides every row from a bare connection.
            async with WatchesStore(engine).tx() as c:
                await c.execute(sa.update(file_watches).values(lease_owner="chk_other"))

        reader.on_get = taken
        lost = await checks.check(watch_id)
        events = await WatchesStore(engine).events(watch_id, after=2)
    assert lost.status == "failed" and events == []
    assert await _entries(engine, tenant, watch_id) == {"drv!a": (2, False)}


async def test_a_file_too_large_is_one_failed_event_its_entry_stays_and_a_rule_is_no_failure(
    engine: AsyncEngine, tmp_path: Path, tenant: str
) -> None:
    reader = Recorded(
        {None: {"items": [_row("a", "e1"), _row("b", "e1")], "next_cursor": None}},
        {"drv!a": _file("a", "e1", b"a"), "drv!b": _file("b", "e1", b"b")},
    )
    checks, watch_id = await _setup(engine, tmp_path, tenant, reader)
    with isolation.scope(tenant, TEAM):
        await checks.check(watch_id)
        # A week on the check lists the folder whole: b grew past what the listing takes in; c is new and refused at
        # fetch for its size; d is left out by the folder's rule, which is not a failure.
        clock[0] = datetime(2026, 12, 2, 9, 0, tzinfo=UTC)
        reader.pages = {
            None: {
                "items": [
                    _row("a", "e1"),
                    _row("b", "e2", skipped="Larger than 25 MB", skipped_code="TOO_LARGE", size=31457280),
                    _row("c", "e1", size=19922944),
                    _row("d", "e1", skipped="Left out by the folder's rule"),
                ],
                "next_cursor": None,
            }
        }
        reader.got["drv!c"] = Answer(False, code="RESPONSE_TOO_LARGE", message="The answer is over 25 MB.")
        outcome = await checks.check(watch_id)
        events = await WatchesStore(engine).events(watch_id, after=2)
    assert (outcome.status, outcome.failed, outcome.removed) == ("success", 2, 0)
    assert sorted((e.kind, e.path, e.size) for e in events) == [
        ("failed", "b.pdf", 31457280),
        ("failed", "c.pdf", 19922944),
    ]
    assert await _entries(engine, tenant, watch_id) == {"drv!a": (1, False), "drv!b": (1, False)}


async def test_each_check_says_why_it_stopped_and_keeps_the_place_until_it_brings_the_file(
    engine: AsyncEngine, tmp_path: Path, tenant: str
) -> None:
    reader = Recorded(
        {None: {"items": [_row("a", "e1")], "next_cursor": None, "cursor": "delta-1"}},
        {"drv!a": _file("a", "e1", b"a")},
    )
    checks, watch_id = await _setup(engine, tmp_path, tenant, reader)
    # A second watch of another folder, checked in the same background pass while the first's connection is unhealthy.
    elsewhere = Recorded({None: {"items": [_row("z", "e1")], "next_cursor": None}}, {"drv!z": _file("z", "e1", b"z")})
    elsewhere.rows = [{**DECLARED, "connectionStatus": "needs_reconnect"}]
    other, other_id = await _setup(engine, tmp_path, tenant, elsewhere, watch_id=f"wat_{tenant}_2")
    with isolation.scope(tenant, TEAM):
        assert (await checks.check(watch_id)).status == "success"
        reader.changes = {"delta-1": {"items": [_row("a", "e2")], "next_cursor": None, "cursor": "delta-2"}}
        said: list[tuple[str, str]] = []
        for answer in (
            Answer(False, code="RATE_LIMITED", message="Too many requests."),
            Answer(False, code="UPSTREAM_UNREACHABLE", message="tools-service did not answer."),
            Answer(False, code="ACCESS_DENIED", message="The file is locked for editing."),
        ):
            reader.got["drv!a"] = answer
            outcome = await checks.check(watch_id)
            said.append((outcome.status, outcome.code))
        # Every check lists the changes from where the last finished check left them, so the change is not dropped.
        assert [a.get("cursor") for t, a in reader.calls if t == DECLARED["changesTool"]] == ["delta-1"] * 3
        assert said == [("partial", "rate_limited"), ("refused", "unreachable"), ("partial", "fetch_failed")]
        # The sign-in is refused; the next check, with the connection still unhealthy, says so too.
        reader.changes = {"delta-1": Answer(False, code="AUTH_EXPIRED", message="The token expired.")}
        first = await checks.check(watch_id)
        watches = WatchesStore(engine)
        for w in (watch_id, other_id):
            assert await watches.request_check(w, NOW, audit={"actor": "a", "action": "x", "summary": "", "detail": {}})
        # The pass reads every tenant's asked watches, so another test's asked check may be counted too.
        assert await other.run_asked() >= 2
        row, other_row = await watches.get(watch_id), await watches.get(other_id)
        assert row is not None and other_row is not None
        reader.changes = {"delta-1": {"items": [_row("a", "e2")], "next_cursor": None, "cursor": "delta-2"}}
        reader.got["drv!a"] = _file("a", "e2", b"a, paid")
        last = await checks.check(watch_id)
    assert (first.status, first.code) == ("refused", "needs_reconnect")
    assert (row.last_outcome or {}).get("code") == "needs_reconnect"
    assert (other_row.last_outcome or {}).get("status") == "success"
    assert (last.status, last.brought) == ("success", 1)
    assert await _entries(engine, tenant, watch_id) == {"drv!a": (2, False)}


async def test_a_file_that_fails_every_fetch_is_one_failed_event_and_the_check_settles_and_removes(
    engine: AsyncEngine, tmp_path: Path, tenant: str
) -> None:
    reader = Recorded(
        {None: {"items": [_row("a", "e1"), _row("c", "e1")], "next_cursor": None}},
        {"drv!a": _file("a", "e1", b"a"), "drv!c": _file("c", "e1", b"c")},
    )
    checks, watch_id = await _setup(engine, tmp_path, tenant, reader)
    with isolation.scope(tenant, TEAM):
        await checks.check(watch_id)
        # A week on the folder is listed whole: c was deleted, and b is new but locked, so every fetch of it fails.
        clock[0] = datetime(2026, 12, 2, 9, 0, tzinfo=UTC)
        reader.pages = {None: {"items": [_row("a", "e1"), _row("b", "e1")], "next_cursor": None}}
        reader.got["drv!b"] = Answer(False, code="ACCESS_DENIED", message="The file is locked for editing.")
        said = [(o.status, o.code, o.removed) for o in [await checks.check(watch_id) for _ in range(4)]]
        row = await WatchesStore(engine).get(watch_id)
        # Its version changes at the source: fetched again, and brought in.
        reader.pages = {None: {"items": [_row("a", "e1"), _row("b", "e2")], "next_cursor": None}}
        reader.got["drv!b"] = _file("b", "e2", b"b")
        clock[0] = datetime(2026, 12, 10, 9, 0, tzinfo=UTC)
        last = await checks.check(watch_id)
        events = await WatchesStore(engine).events(watch_id, after=2)
    # Tried on three checks, then left until it changes: the third settles, so the full listing removes c.
    assert said == [
        ("partial", "fetch_failed", 0),
        ("partial", "fetch_failed", 0),
        ("success", "", 1),
        ("success", "", 0),
    ]
    assert reader.fetched().count("drv!b") == 4
    assert row is not None and row.place.get("last_full_at") == "2026-12-02T09:00:00+00:00"
    assert [(e.kind, e.path) for e in events] == [("failed", "b.pdf"), ("removed", "c.pdf"), ("new", "Invoices/b.pdf")]
    assert (last.status, last.brought) == ("success", 1)


async def test_a_file_refused_for_size_at_either_limit_is_one_failed_event_with_one_wording(
    engine: AsyncEngine, tmp_path: Path, tenant: str
) -> None:
    reader = Recorded(
        {None: {"items": [_row("a", "e1")], "next_cursor": None}},
        {"drv!a": _file("a", "e1", b"a")},
    )
    checks, watch_id = await _setup(engine, tmp_path, tenant, reader)

    def listing(c_size: int, c_etag: str) -> dict[str | None, Any]:
        # b is over the listing's limit; c is listed under it, but its answer at fetch is over the gateway's.
        return {
            None: {
                "items": [
                    _row("a", "e1"),
                    _row("b", "e1", skipped="Larger than 25 MB", skipped_code="TOO_LARGE", size=31457280),
                    _row("c", c_etag, size=c_size),
                ],
                "next_cursor": None,
            }
        }

    with isolation.scope(tenant, TEAM):
        await checks.check(watch_id)
        clock[0] = datetime(2026, 12, 2, 9, 0, tzinfo=UTC)
        reader.pages = listing(20971520, "e1")
        reader.got["drv!c"] = Answer(False, code="RESPONSE_TOO_LARGE", message="The answer is over 25 MB.")
        first = await checks.check(watch_id)
        # Listed whole again a week on at the same sizes: nothing new to say, and c is not fetched again.
        clock[0] = datetime(2026, 12, 10, 9, 0, tzinfo=UTC)
        await checks.check(watch_id)
        # c grows, a new version at the source: it is said once more.
        reader.pages = listing(22020096, "e2")
        clock[0] = datetime(2026, 12, 18, 9, 0, tzinfo=UTC)
        await checks.check(watch_id)
        events = await WatchesStore(engine).events(watch_id, after=1)
    assert [(e.kind, e.path, e.code, e.reason) for e in events] == [
        ("failed", "b.pdf", "too_large", "Larger than 25 MB"),
        ("failed", "c.pdf", "too_large", "Larger than 25 MB"),
        ("failed", "c.pdf", "too_large", "Larger than 25 MB"),
    ]
    assert [e.size for e in events][-1] == 22020096
    assert [f.get("code") for f in first.failures] == ["too_large", "too_large"]
    assert reader.fetched().count("drv!c") == 2
