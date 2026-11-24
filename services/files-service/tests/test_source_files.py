# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""A watched folder's files in the store, by failure mode: the same bytes in two folders folded into one entry, or an
access list nobody read stored the same as one that lists nobody; the same bytes saved again at the source made a
version, or a rename made a second entry. A changed file's version 2 waiting on its own scan is in
test_watch_routes.py, through the download it guards."""

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


async def test_the_same_bytes_in_two_folders_are_two_entries_with_their_own_access_lists(
    engine: AsyncEngine, tenant: str
) -> None:
    store = FilesStore(engine)
    with isolation.scope(tenant, TEAM):
        one, _ = await store.put_source_version(TEAM, _new(f"fil_{tenant}_1", tenant), _found("k1"), _bytes("a"))
        two, _ = await store.put_source_version(
            TEAM, _new(f"fil_{tenant}_2", tenant), _found("k2", "Archive/inv-0042.pdf", allowed=[]), _bytes("a")
        )
        a, b = await store.get(one), await store.get(two)
    assert one != two
    assert a is not None and b is not None
    assert (a.file.access_list, b.file.access_list, b.file.access_read_at) == (None, [], NOW)


async def test_the_same_bytes_again_make_no_version_and_a_rename_keeps_the_entry(
    engine: AsyncEngine, tenant: str
) -> None:
    store = FilesStore(engine)
    file_id = f"fil_{tenant}_1"
    with isolation.scope(tenant, TEAM):
        first = await store.put_source_version(TEAM, _new(file_id, tenant), _found("k1"), _bytes("a"))
        moved = await store.put_source_version(
            TEAM, _new("unused", tenant), _found("k1", "Invoices/2026/inv-0042-paid.pdf"), _bytes("a")
        )
        row = await store.get(file_id)
    assert (first, moved) == ((file_id, 1), (file_id, None))
    assert row is not None and (row.file.name, row.file.source_path, row.file.version_count) == (
        "inv-0042-paid.pdf",
        "Invoices/2026/inv-0042-paid.pdf",
        1,
    )
