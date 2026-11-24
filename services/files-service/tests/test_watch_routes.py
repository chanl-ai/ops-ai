# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The watched folders routes, by failure mode: a Viewer adds, changes, checks or deletes a watch (watches.manage is
Admin's and Builder's), and another team reads, changes, checks or deletes a watch, its events or the files it brought
in; and a watched file's versions: a late verdict on an older version clears a newer one never scanned, an older
version cannot be read while the newest waits, and a hold or a delete reaches only the newest version's bytes, or the
bytes of another entry holding the same ones."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import sqlalchemy as sa

from ops_files.__main__ import RETENTION_CLASSES
from ops_files.service import FilesConfig
from ops_files.store import AsyncEngine, FilesStore, SourceFile, WatchesStore
from ops_files.store.files import service_outbox
from ops_files.tenant_files import TenantFiles
from ops_identity import dev_service_signer, mint_service_token
from ops_service_kit.http import JsonValue
from ops_sources import Answer
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
# A watch of a source that reads pages, not folders of files.
PAGES: dict[str, JsonValue] = {"plugin": "confluence", "source": "pages", "values": {}}
NOW = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
WATCH = {
    "name": "Supplier invoices",
    "plugin": "sharepoint",
    "source": "files",
    "connectionId": "con_1",
    "values": {"sites": ["Finance"], "libraries": ["Invoices"]},
}


class Declaring:
    """tools-service's declared sources for the team: SharePoint's folder source on the team's connection."""

    rows: ClassVar[list[dict[str, JsonValue]]] = [
        {
            "plugin": "sharepoint",
            "source": "files",
            "title": "SharePoint and OneDrive",
            "connectionId": "con_1",
            "connectionStatus": "healthy",
            "signIn": "team",
            "files": True,
            "inputs": {
                "sites": {"type": "array", "required": False},
                "libraries": {"type": "array", "required": False},
            },
        },
        # A knowledge source Files cannot watch: it reads pages, not folders of files.
        {
            "plugin": "confluence",
            "source": "pages",
            "title": "Confluence pages",
            "connectionId": "con_1",
            "connectionStatus": "healthy",
            "signIn": "team",
            "inputs": {},
        },
    ]

    async def declared(self, tenant_id: str, team_id: str) -> list[dict[str, JsonValue]]:
        return self.rows

    async def call(
        self, tenant_id: str, team_id: str, tool: str | None, args: dict[str, JsonValue], *, act: str
    ) -> Answer:
        raise AssertionError("a route never calls a tool")


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
    async with client(reader=Declaring()) as builder, client(role="viewer", reader=Declaring()) as viewer:
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
    async with client(reader=Declaring()) as builder:
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
    async with client(reader=Declaring()) as builder:
        made = _data(await builder.post("/v1/watches", json={**WATCH, "names": names}, headers=OPS))
        await _brought_in(engine, tmp_path, tenant, made["id"])
        [row] = _data(await builder.get("/v1/watches", headers=OPS))["data"]
        assert row["folders"] == [
            {"input": "libraries", "id": "Invoices", "name": "Supplier invoices"},
        ], row["folders"]
        assert (row["filesInFiles"], row["inUse"], row["connectionId"]) == (1, False, "con_1"), row
        # A watch saved with no names (the SDK and CLI) lists no named folders; the console counts its ids instead.
        # Saved with no connection, it reads through the team's.
        bare_in = {k: v for k, v in WATCH.items() if k != "connectionId"}
        bare = _data(await builder.post("/v1/watches", json={**bare_in, "name": "No names"}, headers=OPS))
        assert (bare["folders"], bare["connectionId"]) == ([], "con_1"), bare
        # Settings the source does not declare, an app the team has not turned on, and another connection are refused.
        refused = [
            await builder.post("/v1/watches", json={**WATCH, "values": {"site": "Finance"}}, headers=OPS),
            await builder.post("/v1/watches", json={**WATCH, "plugin": "box"}, headers=OPS),
            await builder.post("/v1/watches", json={**WATCH, **PAGES}, headers=OPS),
            await builder.post("/v1/watches", json={**WATCH, "connectionId": "con_other"}, headers=OPS),
            await builder.patch(f"/v1/watches/{made['id']}", json={"values": {"libraries": "Invoices"}}, headers=OPS),
        ]
        assert [(r.status_code, r.json()["error"]["code"]) for r in refused] == [
            (400, "invalid_source_values"),
            (400, "source_not_offered"),
            (400, "source_not_offered"),
            (400, "connection_mismatch"),
            (400, "invalid_source_values"),
        ], [r.text for r in refused]
        changed = await builder.patch(
            f"/v1/watches/{made['id']}", json={"values": {"libraries": ["Invoices", "Archive"]}}, headers=OPS
        )
        assert _data(changed)["folders"] == [
            {"input": "libraries", "id": "Invoices", "name": "Supplier invoices"},
            {"input": "libraries", "id": "Archive", "name": "Archive"},
        ], _data(changed)


def _found(watch_id: str, key: str, path: str) -> SourceFile:
    return {"key_hash": key, "source_id": f"drv!{key}", "source_path": path, "name": path.rsplit("/", 1)[-1],
            "mime": "application/pdf", "access_list": None, "access_read_at": NOW, "watch_id": watch_id,
            "marker": "e1"}  # fmt: skip


async def test_each_version_of_a_watched_file_is_scanned_read_held_and_deleted_on_its_own(
    client: Client,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
    tmp_path: Path,
) -> None:
    objects = LocalObjectStore(tmp_path / "objects", signing_key=b"k" * 32)
    config = FilesConfig(retention_classes=RETENTION_CLASSES, default_retention_class="standard")
    files = TenantFiles(objects, FilesStore(engine), config, scanning="hook")
    token = mint_service_token(
        dev_service_signer(), service="scanner", audience="files", tenant_id=tenant, scopes=["files:decide"]
    )
    scanner = {"Authorization": f"Bearer {token}"}
    paid = PDF + b"% paid"
    async with client(scanning="hook", admin=True, reader=Declaring()) as admin:
        watch_id = _data(await admin.post("/v1/watches", json=WATCH, headers=OPS))["id"]
        with isolation.scope(tenant, "team_ops"):
            file_id, _ = await files.put_source(tenant, "team_ops", _found(watch_id, "k1", "Invoices/a.pdf"), PDF,
                                                actor="watch:w")  # fmt: skip
        verdict = {"fileId": file_id, "status": "clean", "engine": "clamav", "version": 1}
        assert (await admin.post("/v1/files/scan-results", json=verdict, headers=scanner)).status_code == 200
        detail = _data(await admin.get(f"/v1/files/{file_id}", headers=OPS))
        # A watched folder is often a finance or claims library, so its files start confidential.
        assert detail["sensitivity"] == "confidential"
        with isolation.scope(tenant, "team_ops"):
            await files.put_source(tenant, "team_ops", _found(watch_id, "k1", "Invoices/a.pdf"), paid, actor="watch:w")
            # Another folder holds the same bytes as version 2: its own entry, kept when the first is deleted.
            other, _ = await files.put_source(tenant, "team_ops", _found(watch_id, "k2", "Archive/a.pdf"), paid,
                                              actor="watch:w")  # fmt: skip
        content = f"/v1/files/{file_id}/content"
        assert (await admin.get(content, headers=OPS)).status_code == 423
        assert (await admin.get(f"{content}?version=1", headers=OPS)).content == PDF
        # The scanner's verdict on version 1 arrives again late: version 2 was never scanned, so it stays unreadable.
        assert (await admin.post("/v1/files/scan-results", json=verdict, headers=scanner)).status_code == 200
        assert (await admin.get(content, headers=OPS)).status_code == 423
        unnamed = {"fileId": file_id, "status": "clean", "engine": "clamav"}
        assert (await admin.post("/v1/files/scan-results", json=unnamed, headers=scanner)).status_code == 400
        digest = hashlib.sha256(paid).hexdigest()
        # A verdict naming version 1 by number and version 2 by digest is refused, and clears neither.
        mixed = {**unnamed, "version": 1, "digest": digest}
        assert (await admin.post("/v1/files/scan-results", json=mixed, headers=scanner)).status_code == 400
        assert (await admin.get(content, headers=OPS)).status_code == 423
        named = {**unnamed, "digest": digest}
        assert (await admin.post("/v1/files/scan-results", json=named, headers=scanner)).status_code == 200
        assert (await admin.get(content, headers=OPS)).content == paid
        with isolation.scope(tenant, "team_ops"):
            row = await FilesStore(engine).get(file_id)
        assert row is not None
        keys = [v.storage_key for v in row.versions]
        hold = {"ids": [file_id], "hold": True, "reason": "Supplier dispute"}
        assert _data(await admin.post("/v1/files/legal-hold", json=hold, headers=OPS))["updated"] == [file_id]
        assert [bool((info := objects.head(k)) and info.legal_hold) for k in keys] == [True, True]
        # A version the check writes while the file is held is held too.
        with isolation.scope(tenant, "team_ops"):
            await files.put_source(tenant, "team_ops", _found(watch_id, "k1", "Invoices/a.pdf"), paid + b" refunded",
                                   actor="watch:w")  # fmt: skip
            held = await FilesStore(engine).get(file_id)
        assert held is not None and len(held.versions) == 3
        assert [bool((info := objects.head(v.storage_key)) and info.legal_hold) for v in held.versions] == [True] * 3
        release = {**hold, "hold": False, "reason": "Settled"}
        assert _data(await admin.post("/v1/files/legal-hold", json=release, headers=OPS))["updated"] == [file_id]
        assert (await admin.delete(f"/v1/files/{file_id}", headers=OPS)).status_code == 204
        assert [objects.head(k) for k in keys] == [None, None]
        await admin.post("/v1/files/scan-results", json={**named, "fileId": other}, headers=scanner)
        assert (await admin.get(f"/v1/files/{other}/content", headers=OPS)).content == paid


def _service(tenant: str, service: str, scopes: list[str]) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service=service, audience="files", tenant_id=tenant, scopes=scopes, team_id="team_ops"
    )
    return {"Authorization": f"Bearer {token}"}


class Uses:
    """agents-service's answer to which live and draft workflows name each watch; None when it cannot be asked."""

    def __init__(self) -> None:
        self.used: dict[str, list[dict[str, JsonValue]]] | None = {}

    async def of(self, tenant: str, team: str, ids: list[str]) -> dict[str, list[dict[str, JsonValue]]] | None:
        return None if self.used is None else {i: self.used.get(i, []) for i in ids}


async def test_agents_service_asks_a_check_and_another_service_is_refused(
    client: Client,  # noqa: F811
    tenant: str,
) -> None:
    async with client(reader=Declaring()) as builder:
        watch_id = _data(await builder.post("/v1/watches", json=WATCH, headers=OPS))["id"]
        by = {"by": "trigger:files:wf_invoices"}
        refused = await builder.post(
            f"/v1/watches/{watch_id}/check", json=by, headers=_service(tenant, "kb", ["files:view"])
        )
        asked = await builder.post(
            f"/v1/watches/{watch_id}/check", json=by, headers=_service(tenant, "agents", ["files:view", "files:check"])
        )
        seen = _data(await builder.get(f"/v1/watches/{watch_id}", headers=OPS))
    assert (refused.status_code, refused.json()["error"]["code"]) == (403, "scope_required"), refused.text
    assert asked.status_code == 202, asked.text
    assert (seen["checking"], seen["lastEvent"]) == (True, 0), seen


async def test_a_watch_a_workflow_uses_is_not_deleted_and_names_the_workflow(
    client: Client,  # noqa: F811
) -> None:
    uses = Uses()
    async with client(reader=Declaring(), watch_uses=uses) as builder:
        watch_id = _data(await builder.post("/v1/watches", json=WATCH, headers=OPS))["id"]
        uses.used = {watch_id: [{"workflowId": "wf_invoices", "name": "Supplier invoice intake", "live": True}]}
        listed = _data(await builder.get("/v1/watches", headers=OPS))["data"][0]
        kept = await builder.delete(f"/v1/watches/{watch_id}", headers=OPS)
        uses.used = None
        unasked = await builder.delete(f"/v1/watches/{watch_id}", headers=OPS)
        uses.used = {}
        gone = await builder.delete(f"/v1/watches/{watch_id}", headers=OPS)
    assert (listed["inUse"], [u["name"] for u in listed["usedBy"]]) == (True, ["Supplier invoice intake"]), listed
    assert (kept.status_code, kept.json()["error"]["code"]) == (409, "watch_in_use"), kept.text
    assert kept.json()["error"]["details"]["usedBy"][0]["workflowId"] == "wf_invoices", kept.text
    assert unasked.status_code == 503, unasked.text
    assert gone.status_code == 204, gone.text
