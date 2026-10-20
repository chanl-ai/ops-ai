# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""files-service's tables on PostgreSQL: the dedupe guarantee holds under concurrent completions, and every read is
held to its tenant."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from ops_files.store import AsyncEngine, FilesStore

DIGEST = "a" * 64
NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


def _upload(file_id: str, tenant: str, team: str = "team_ops") -> dict[str, Any]:
    return {
        "id": file_id,
        "tenant_id": tenant,
        "team": team,
        "name": "statement.pdf",
        "mime": "application/pdf",
        "size": 10,
        "purpose": "chat_attachment",
        "status": "uploading",
        "scan_status": "pending",
        "sensitivity": "confidential",
        "sensitivity_suggested": True,
        "retention_class_id": "standard",
        "immutable": False,
        "storage_backend": "local",
        "storage_container": "local",
        "storage_key": f"{tenant}/{team}/chat_attachment/2026/10/{file_id}",
        "declared_size": 10,
        "uploaded_by": "james@northfieldbank.com",
        "uploaded_at": NOW,
        "version_count": 0,
    }


def _available() -> dict[str, Any]:
    return {"digest": DIGEST, "status": "available", "version_count": 1}


def _version(file_id: str, tenant: str) -> dict[str, Any]:
    return {
        "version": 1,
        "digest": DIGEST,
        "size": 10,
        "storage_key": f"{tenant}/team_ops/chat_attachment/2026/10/{file_id}",
        "uploaded_by": "james@northfieldbank.com",
        "uploaded_at": NOW,
        "current": True,
    }


async def test_two_completions_of_the_same_bytes_leave_one_available_file(engine: AsyncEngine, tenant: str) -> None:
    store = FilesStore(engine)
    ids = [f"fil_{tenant}_one", f"fil_{tenant}_two"]
    for file_id in ids:
        await store.insert_upload(_upload(file_id, tenant))
    results = await asyncio.gather(
        *(store.make_available(tenant, file_id, _available(), _version(file_id, tenant)) for file_id in ids)
    )
    # Exactly one completion won; the other was handed the winner's id and wrote nothing.
    assert results.count(None) == 1
    winner = ids[results.index(None)]
    loser = ids[1 - results.index(None)]
    assert results[ids.index(loser)] == winner
    listed = await store.list(tenant, "team_ops", page=1, page_size=10)
    assert [row["id"] for row in listed.rows] == [winner]
    loser_row = await store.get(tenant, loser)
    assert loser_row is not None and loser_row["status"] == "uploading"


async def test_the_same_bytes_in_another_team_are_a_second_file(engine: AsyncEngine, tenant: str) -> None:
    store = FilesStore(engine)
    ops, sec = f"fil_{tenant}_ops", f"fil_{tenant}_sec"
    await store.insert_upload(_upload(ops, tenant))
    await store.insert_upload(_upload(sec, tenant, team="team_security"))
    assert await store.make_available(tenant, ops, _available(), _version(ops, tenant)) is None
    assert await store.make_available(tenant, sec, _available(), _version(sec, tenant)) is None


async def test_a_file_is_not_found_from_another_tenant(engine: AsyncEngine, tenant: str) -> None:
    store = FilesStore(engine)
    mine = f"fil_{tenant}_mine"
    await store.insert_upload(_upload(mine, tenant))
    assert await store.get(f"{tenant}_other", mine) is None
    assert (await store.list(f"{tenant}_other", "team_ops", page=1, page_size=10)).total == 0
