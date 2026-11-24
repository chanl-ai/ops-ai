# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""A watched folder's files in the store, by failure mode: the same bytes in two folders folded into one entry; the
same bytes saved again at the source made a version; a changed file got no version 2, or one readable before its
scan; a rename made a second entry; and an access list nobody read stored the same as one that lists nobody."""

from __future__ import annotations

from datetime import UTC, datetime

from ops_files.store import AsyncEngine, FilesStore, NewUpload, SourceFile, SourceVersion
from ops_store import isolation

TEAM = "team_ap"
NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)


def _new(file_id: str, tenant: str) -> NewUpload:
    return {
        "id": file_id, "tenant_id": tenant, "team": TEAM, "name": "inv-0042.pdf", "mime": "application/pdf",
        "size": 0, "purpose": "source_file", "status": "available", "scan_status": "pending",
        "sensitivity": "internal", "sensitivity_suggested": True, "retention_class_id": "standard",
        "immutable": False, "storage_backend": "local", "storage_container": "local",
        "storage_key": f"{tenant}/{TEAM}/source_file/{file_id}", "declared_size": 0,
        "uploaded_by": "watch:wat_invoices", "uploaded_at": NOW, "version_count": 0,
    }  # fmt: skip


def _found(key: str, path: str = "Invoices/inv-0042.pdf", allowed: list[str] | None = None) -> SourceFile:
    return {"key_hash": key, "source_id": f"item-{key}", "source_path": path, "name": path.rsplit("/", 1)[-1],
            "mime": "application/pdf", "access_list": allowed, "access_read_at": NOW}  # fmt: skip


def _bytes(digest: str) -> SourceVersion:
    return {
        "digest": digest * 64,
        "size": 1200,
        "storage_key": f"k/{digest}",
        "source_tag": f"etag-{digest}",
        "at": NOW,
    }


async def test_the_same_bytes_in_two_folders_are_two_entries(engine: AsyncEngine, tenant: str) -> None:
    store = FilesStore(engine)
    with isolation.scope(tenant, TEAM):
        one, _ = await store.put_source_version(TEAM, _new(f"fil_{tenant}_1", tenant), _found("k1"), _bytes("a"))
        two, _ = await store.put_source_version(
            TEAM, _new(f"fil_{tenant}_2", tenant), _found("k2", "Archive/inv-0042.pdf"), _bytes("a")
        )
    assert one != two


async def test_the_same_bytes_saved_again_make_no_version(engine: AsyncEngine, tenant: str) -> None:
    store = FilesStore(engine)
    with isolation.scope(tenant, TEAM):
        first = await store.put_source_version(TEAM, _new(f"fil_{tenant}_1", tenant), _found("k1"), _bytes("a"))
        again = await store.put_source_version(TEAM, _new(f"fil_{tenant}_x", tenant), _found("k1"), _bytes("a"))
    assert first == (f"fil_{tenant}_1", 1) and again == (f"fil_{tenant}_1", None)


async def test_changed_bytes_are_version_two_waiting_on_its_scan(engine: AsyncEngine, tenant: str) -> None:
    store = FilesStore(engine)
    file_id = f"fil_{tenant}_1"
    with isolation.scope(tenant, TEAM):
        await store.put_source_version(TEAM, _new(file_id, tenant), _found("k1"), _bytes("a"))
        await store.update(file_id, {"scan_status": "clean"})
        await store.set_version_scan(file_id, 1, "clean", NOW)
        assert await store.put_source_version(TEAM, _new("unused", tenant), _found("k1"), _bytes("b")) == (file_id, 2)
        row = await store.get(file_id)
    assert row is not None and row.file.version_count == 2
    assert [(v.version, v.scan_status, v.current) for v in row.versions] == [(1, "clean", False), (2, "pending", True)]


async def test_a_rename_keeps_the_entry(engine: AsyncEngine, tenant: str) -> None:
    store = FilesStore(engine)
    file_id = f"fil_{tenant}_1"
    with isolation.scope(tenant, TEAM):
        await store.put_source_version(TEAM, _new(file_id, tenant), _found("k1"), _bytes("a"))
        moved = await store.put_source_version(
            TEAM, _new("unused", tenant), _found("k1", "Invoices/2026/inv-0042-paid.pdf"), _bytes("a")
        )
        row = await store.get(file_id)
    assert moved == (file_id, None)
    assert row is not None and (row.file.name, row.file.source_path) == (
        "inv-0042-paid.pdf",
        "Invoices/2026/inv-0042-paid.pdf",
    )


async def test_the_access_list_keeps_not_known_apart_from_empty(engine: AsyncEngine, tenant: str) -> None:
    store = FilesStore(engine)
    with isolation.scope(tenant, TEAM):
        unknown, _ = await store.put_source_version(TEAM, _new(f"fil_{tenant}_1", tenant), _found("k1"), _bytes("a"))
        nobody, _ = await store.put_source_version(
            TEAM, _new(f"fil_{tenant}_2", tenant), _found("k2", allowed=[]), _bytes("b")
        )
        a, b = await store.get(unknown), await store.get(nobody)
    assert a is not None and b is not None
    assert (a.file.access_list, b.file.access_list, b.file.access_read_at) == (None, [], NOW)
