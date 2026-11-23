# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""What files-service answers, byte for byte where it matters to a caller: the datetime format, which keys are null
and which are left out, and every error object its routes return. The models behind the routes may change; these
replies may not, unless the change is listed in docs/architecture/migration/api-changes.md."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx

from ops_storage.local import LocalObjectStore
from tests import test_api
from tests.test_api import OPS, PDF, Client, _kb, _upload  # pyright: ignore[reportPrivateUsage]

# The files tests' app fixture, defined beside the API tests.
client = test_api.client

# What a datetime reads as in every reply: UTC, with a Z, microseconds only when there are some.
WHEN = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{1,6})?Z$")
DAY = re.compile(r"^\d{4}-\d\d-\d\d$")

DETAIL_KEYS = {
    "id", "name", "mime", "size", "digest", "purpose", "team", "uploadedBy", "uploadedAt", "scan", "sensitivity",
    "sensitivitySuggested", "retention", "legalHold", "immutable", "referenceCount", "versionCount", "storage", "data",
    "versions", "references", "deleteBlockedBy", "canEdit", "canDelete", "canPublish",
}  # fmt: skip
# A list row is the detail without the keys only the detail route sets.
ROW_KEYS = DETAIL_KEYS - {"versions", "references", "deleteBlockedBy", "canEdit", "canDelete", "canPublish"}


def _data(r: httpx.Response) -> Any:
    assert r.status_code < 300, r.text
    return r.json()["data"]


async def _clean_file(c: httpx.AsyncClient) -> dict[str, Any]:
    ticket = await _upload(c)
    return _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))


async def test_replies_keep_their_datetime_format_and_their_null_and_missing_keys(client: Client) -> None:
    async with client(admin=True) as c:
        health = await c.get("/health")
        ticket = _data(
            await c.post(
                "/v1/files/uploads",
                json={"name": "s.pdf", "size": len(PDF), "mime": "application/pdf", "purpose": "chat_attachment"},
                headers=OPS,
            )
        )
        await c.put(ticket["uploadUrl"], content=PDF, headers={**OPS, **ticket["headers"]})
        done = _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))
        file_id = done["file"]["id"]
        detail = _data(await c.get(f"/v1/files/{file_id}", headers=OPS))
        page = _data(await c.get("/v1/files", headers=OPS))
        link = _data(await c.post(f"/v1/files/{file_id}/download-url", headers=OPS))
        limits = _data(await c.get("/v1/files/limits", headers=OPS))
        read = _data(await c.post(f"/v1/files/{file_id}/read-requests", json={}, headers=OPS))

    assert (health.status_code, health.json()) == (200, {"status": "ok"})
    assert set(ticket) == {"fileId", "uploadUrl", "method", "headers", "expiresAt"} and WHEN.match(ticket["expiresAt"])
    assert set(done) == {"file", "deduplicated"}
    # The upload's answer is the detail with no flags: they are set on the detail route only, and sent as null.
    assert set(done["file"]) == DETAIL_KEYS
    assert [done["file"][k] for k in ("deleteBlockedBy", "canEdit", "canDelete", "canPublish")] == [None] * 4

    assert set(detail) == DETAIL_KEYS
    assert {k for k, v in detail.items() if v is None} == {"legalHold", "data", "deleteBlockedBy"}
    assert WHEN.match(detail["uploadedAt"]) and WHEN.match(detail["scan"]["at"])
    assert set(detail["scan"]) == {"status", "engine", "at", "detail"} and detail["scan"]["detail"] == "scanning is off"
    assert DAY.match(detail["retention"]["deleteAfter"])
    assert set(detail["storage"]) == {"backend", "environment", "container", "key", "region", "encryption", "locked"}
    [version] = detail["versions"]
    assert set(version) == {"version", "digest", "size", "uploadedBy", "uploadedAt", "current"}
    assert WHEN.match(version["uploadedAt"]) and detail["references"] == []

    [row] = page["data"]
    assert set(row) == ROW_KEYS and row["uploadedAt"] == detail["uploadedAt"]
    assert {k for k, v in row.items() if v is None} == {"legalHold", "data"}
    assert set(page) == {"data", "pagination", "facets", "viewCounts"}

    assert set(link) == {"url", "expiresAt", "ttlSeconds"} and WHEN.match(link["expiresAt"])
    # No storage settings saved: no purpose limits beyond the configured ones, which this test configures none of.
    assert limits == {"perPurpose": [], "scanning": False}
    assert set(read) == {
        "key", "fileId", "documentTypeId", "version", "status", "runId", "requestedBy", "requestedAt",
    }  # fmt: skip
    assert WHEN.match(read["requestedAt"]) and (read["documentTypeId"], read["version"]) == (None, None)


async def test_a_held_file_shows_its_hold_and_why_it_cannot_be_deleted(client: Client) -> None:
    async with client(admin=True) as c:
        file_id = (await _clean_file(c))["file"]["id"]
        hold = {"ids": [file_id], "hold": True, "reason": "Matter 114"}
        held = _data(await c.post("/v1/files/legal-hold", json=hold, headers=OPS))
        detail = _data(await c.get(f"/v1/files/{file_id}", headers=OPS))
        [row] = _data(await c.get("/v1/files", headers=OPS))["data"]
    assert held == {"updated": [file_id], "skipped": []}
    assert set(detail["legalHold"]) == {"by", "at", "reason"} and WHEN.match(detail["legalHold"]["at"])
    assert row["legalHold"] == detail["legalHold"]
    assert (detail["deleteBlockedBy"], detail["canDelete"]) == ("Under legal hold: Matter 114", False)


def _error(r: httpx.Response, *ids: str) -> tuple[int, str, str]:
    body = r.json()
    assert body["success"] is False and set(body) == {"success", "error"}, r.text
    error = body["error"]
    assert set(error) == {"code", "message", "status", "requestId", "kind", "retryable"}, r.text
    assert error["status"] == r.status_code and error["requestId"].startswith("req_"), r.text
    message = error["message"]
    for n, value in enumerate(ids):
        message = message.replace(value, f"{{{n}}}")
    return r.status_code, error["code"], message


async def test_every_refusal_answers_the_same_error_object(client: Client, tenant: str, tmp_path: Path) -> None:
    """The 415 is pinned with a saved limit in test_storage_settings.py, the 423 below."""
    store = LocalObjectStore(tmp_path / "objects", signing_key=b"k" * 32)
    service = _kb(tenant, "team_ops", ["files:view"])
    async with client(admin=True, store=store) as admin, client(role="chat_user", store=store) as chatter:
        file_id = (await _clean_file(admin))["file"]["id"]
        key = _data(await admin.get(f"/v1/files/{file_id}", headers=OPS))["storage"]["key"]
        new = {"name": "s.pdf", "size": len(PDF), "mime": "application/pdf", "purpose": "chat_attachment"}
        hold = {"ids": [file_id], "hold": True, "reason": "Matter 114"}
        got = [
            await admin.get("/v1/files/fil_missing0000000000000000000000", headers=OPS),
            await chatter.delete(f"/v1/files/{file_id}", headers=OPS),
            await admin.post("/v1/files/uploads", json={**new, "size": 10**12}, headers=OPS),
            await admin.post(f"/v1/files/{file_id}/download-url", json={"ttlSeconds": 10**6}, headers=OPS),
            await chatter.post("/v1/files/legal-hold", json=hold, headers=OPS),
            await admin.post("/v1/files/legal-hold", json={**hold, "reason": " "}, headers=OPS),
            await admin.post("/v1/files/legal-hold", json=hold, headers=OPS),
            await admin.delete(f"/v1/files/{file_id}", headers=OPS),
            await admin.post("/v1/files/legal-hold", json={**hold, "hold": False, "reason": "Closed"}, headers=OPS),
            await admin.post("/v1/files/bulk-delete", json={"ids": [file_id]}, headers=service),
        ]
        store.set_legal_hold(key, True)
        got.append(await admin.delete(f"/v1/files/{file_id}", headers=OPS))
    assert [r.status_code for r in got] == [404, 403, 413, 400, 403, 400, 200, 409, 200, 403, 409]
    assert [_error(r, key, file_id) for r in got if r.status_code >= 400] == [
        (404, "not_found", "File was not found."),
        (403, "role_required", "Your role in this team does not delete files."),
        (413, "payload_too_large", "This file is over the 100 MB a chat attachment can be."),
        (400, "validation_failed", "download links last at most 300 seconds"),
        (403, "forbidden", "only an admin of the file's team places or releases a legal hold"),
        (400, "validation_failed", "a legal hold needs a reason"),
        (409, "conflict", "{1} is under legal hold"),
        (403, "scope_required", "This files route does not take service tokens."),
        (409, "locked_in_storage", "{0} is under legal hold"),
    ]


async def test_a_file_not_scanned_clean_is_locked(client: Client) -> None:
    async with client(scanning="hook") as c:
        file_id = (await _clean_file(c))["file"]["id"]
        locked = await c.post(f"/v1/files/{file_id}/download-url", headers=OPS)
    assert _error(locked, file_id) == (423, "locked", "{0} scan is pending")
