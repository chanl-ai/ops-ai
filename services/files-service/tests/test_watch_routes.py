# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The watched folders routes, by failure mode: a Viewer adds, changes, checks or deletes a watch (watches.manage is
Admin's and Builder's), and another team reads, changes, checks or deletes a watch, its events or the files it brought
in."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from ops_files.__main__ import RETENTION_CLASSES
from ops_files.service import FilesConfig
from ops_files.store import AsyncEngine, FilesStore, WatchesStore
from ops_files.store.files import service_outbox
from ops_files.tenant_files import TenantFiles
from ops_storage.local import LocalObjectStore
from ops_store import isolation

from .test_api import (  # pyright: ignore[reportPrivateUsage]
    OPS,
    PDF,
    Client,
    _data,  # pyright: ignore[reportPrivateUsage]
    _upload,  # pyright: ignore[reportPrivateUsage]
    client,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)

CARDS = {"X-Team-Id": "team_cards"}
WATCH = {
    "name": "Supplier invoices",
    "plugin": "sharepoint",
    "source": "files",
    "connectionId": "con_1",
    "values": {"site": "Finance", "libraries": ["Invoices"]},
}


async def _brought_in(engine: AsyncEngine, tmp_path: Path, tenant: str, watch_id: str) -> str:
    """A file the watch's check brought in, and one numbered event for it, as a check writes them."""
    config = FilesConfig(retention_classes=RETENTION_CLASSES, default_retention_class="standard")
    files = TenantFiles(
        LocalObjectStore(tmp_path / "objects", signing_key=b"k" * 32), FilesStore(engine), config, scanning="off"
    )
    now = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
    with isolation.scope(tenant, "team_ops"):
        file_id, _ = await files.put_source(
            tenant,
            "team_ops",
            {
                "key_hash": "k1",
                "source_id": "drv!a",
                "source_path": "Invoices/a.pdf",
                "name": "a.pdf",
                "mime": "application/pdf",
                "access_list": None,
                "access_read_at": now,
                "watch_id": watch_id,
                "marker": "e1",
                "changed_at": datetime(2026, 11, 24, 8, 52, tzinfo=UTC),
            },
            PDF,
            actor=f"watch:{watch_id}",
        )
        watches = WatchesStore(engine)
        assert await watches.claim(watch_id, owner="chk_1", seconds=60)
        event = {"file_id": file_id, "version": 1, "kind": "new", "reason": None, "size": len(PDF),
                 "path": "Invoices/a.pdf", "at": now}  # fmt: skip
        assert await watches.add_events(watch_id, owner="chk_1", events=[event]) == 1  # pyright: ignore[reportArgumentType]
        await watches.finish(watch_id, owner="chk_1", outcome={"status": "success", "brought": 1}, at=now)
    return file_id


async def test_a_viewer_cannot_change_a_watch_and_another_team_cannot_reach_it(
    client: Client,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
    tmp_path: Path,
) -> None:
    async with client() as builder, client(role="viewer") as viewer:
        made = await builder.post("/v1/watches", json=WATCH, headers=OPS)
        assert made.status_code == 201, made.text
        watch_id = _data(made)["id"]
        file_id = await _brought_in(engine, tmp_path, tenant, watch_id)

        # A Viewer reads the team's watches but changes none of them.
        assert [w["id"] for w in _data(await viewer.get("/v1/watches", headers=OPS))["data"]] == [watch_id]
        refused = [
            await viewer.post("/v1/watches", json=WATCH, headers=OPS),
            await viewer.patch(f"/v1/watches/{watch_id}", json={"name": "Renamed"}, headers=OPS),
            await viewer.post(f"/v1/watches/{watch_id}/check", headers=OPS),
            await viewer.delete(f"/v1/watches/{watch_id}", headers=OPS),
        ]
        assert [r.status_code for r in refused] == [403] * 4, [r.text for r in refused]

        # Another team, where the same person is a Builder, finds neither the watch, its events nor its file.
        missing = [
            await builder.get(f"/v1/watches/{watch_id}", headers=CARDS),
            await builder.get(f"/v1/watches/{watch_id}/events", headers=CARDS),
            await builder.patch(f"/v1/watches/{watch_id}", json={"name": "Renamed"}, headers=CARDS),
            await builder.post(f"/v1/watches/{watch_id}/check", headers=CARDS),
            await builder.delete(f"/v1/watches/{watch_id}", headers=CARDS),
            await builder.get(f"/v1/files/{file_id}", headers=CARDS),
        ]
        assert [r.status_code for r in missing] == [404] * 6, [r.text for r in missing]
        assert _data(await builder.get("/v1/watches", headers=CARDS))["data"] == []

        # The other team's delete removed nothing: the watch, its name and its event are all still there.
        kept = _data(await builder.get(f"/v1/watches/{watch_id}", headers=OPS))
        events = _data(await builder.get(f"/v1/watches/{watch_id}/events", headers=OPS))["data"]
        assert (kept["name"], kept["lastCheck"]["brought"]) == ("Supplier invoices", 1), kept
        assert [(e["kind"], e["fileId"]) for e in events] == [("new", file_id)], events

        # Check now: taken once, written to the audit log with the folders, and 409 while it is asked for.
        assert (await builder.post(f"/v1/watches/{watch_id}/check", headers=OPS)).status_code == 202
        again = await builder.post(f"/v1/watches/{watch_id}/check", headers=OPS)
        assert (again.status_code, again.json()["error"]["code"]) == (409, "already_checking"), again.text

    async with engine.connect() as c:
        rows = (await c.execute(sa.select(service_outbox.c.name, service_outbox.c.payload))).all()
    audited = [p["action"] for n, p in rows if n == "audit.recorded" and p["targetId"] == watch_id]
    assert audited == ["files.watch.created", "files.watch.checked"], rows


async def test_the_file_page_names_its_watched_folder_and_an_upload_names_none(
    client: Client,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
    tmp_path: Path,
) -> None:
    """A source file's detail says which watch brought it, where it sits, when the source changed it, and its access
    list as read with "not known" (null) apart from nobody ([]); removed and deleted-watch states keep the entry."""
    async with client() as builder:
        watch_id = _data(await builder.post("/v1/watches", json=WATCH, headers=OPS))["id"]
        file_id = await _brought_in(engine, tmp_path, tenant, watch_id)
        source = _data(await builder.get(f"/v1/files/{file_id}", headers=OPS))["source"]
        assert source == {
            "watchId": watch_id,
            "watchName": "Supplier invoices",
            "path": "Invoices/a.pdf",
            "changedAt": "2026-11-24T08:52:00Z",
            "removedAt": None,
            "accessList": None,
            "accessReadAt": "2026-11-24T09:00:00Z",
        }, source

        uploaded = await _upload(builder)
        done = _data(await builder.post(f"/v1/files/uploads/{uploaded['fileId']}/complete", headers=OPS))
        assert _data(await builder.get(f"/v1/files/{done['file']['id']}", headers=OPS))["source"] is None

        with isolation.scope(tenant, "team_ops"):
            await FilesStore(engine).remove_sources([file_id], datetime(2026, 11, 24, 10, 40, tzinfo=UTC))
        assert (await builder.delete(f"/v1/watches/{watch_id}", headers=OPS)).status_code == 204
        after = _data(await builder.get(f"/v1/files/{file_id}", headers=OPS))["source"]
        assert (after["watchId"], after["watchName"], after["removedAt"]) == (
            watch_id,
            None,
            "2026-11-24T10:40:00Z",
        ), after


async def test_the_list_names_a_watchs_folders_counts_its_files_and_keeps_its_connection(
    client: Client,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
    tmp_path: Path,
) -> None:
    """The Watched folders row shows folder names (not "libraries: 1"), how many of its files are in Files, and the
    connection it was made with; a name for a folder no longer picked is dropped when the folders change."""
    names = {"libraries": {"Invoices": "Supplier invoices", "Elsewhere": "Not picked"}}
    async with client() as builder:
        made = _data(await builder.post("/v1/watches", json={**WATCH, "names": names}, headers=OPS))
        await _brought_in(engine, tmp_path, tenant, made["id"])
        [row] = _data(await builder.get("/v1/watches", headers=OPS))["data"]
        assert row["folders"] == [
            {"input": "libraries", "id": "Invoices", "name": "Supplier invoices"},
        ], row["folders"]
        assert (row["filesInFiles"], row["inUse"], row["connectionId"]) == (1, False, "con_1"), row
        changed = await builder.patch(
            f"/v1/watches/{made['id']}", json={"values": {"libraries": ["Invoices", "Archive"]}}, headers=OPS
        )
        assert _data(changed)["folders"] == [
            {"input": "libraries", "id": "Invoices", "name": "Supplier invoices"},
            {"input": "libraries", "id": "Archive", "name": "Archive"},
        ], _data(changed)
