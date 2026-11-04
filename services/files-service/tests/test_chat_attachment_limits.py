# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The limits files-service starts with for a chat attachment, by failure mode: a file documents-service cannot
read is stored, so the agent it is attached for is told nothing; a file over chat's size limit is accepted."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from ops_files.__main__ import files_config
from ops_files.app import create_files_app
from ops_files.store import AsyncEngine, FilesStore
from ops_files.tenant_files import TenantFiles
from ops_identity import Auth
from ops_service_kit.settings import Settings
from ops_storage.local import LocalObjectStore
from tests.test_api import OPS, PDF, sign_in

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _client(engine: AsyncEngine, tenant: str, tmp_path: Path) -> httpx.AsyncClient:
    files = TenantFiles(
        LocalObjectStore(tmp_path / "objects", signing_key=b"k" * 32),
        FilesStore(engine),
        files_config(Settings()),
        scanning="off",
    )
    auth = Auth.for_dev(Settings(), audience="files", name="james", email="james@harborpine.example", tenant_id=tenant)
    app = create_files_app(files, engine=engine, auth=auth)
    sign_in(app, tenant, "builder")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://files")


async def _put(c: httpx.AsyncClient, body: bytes, name: str, mime: str) -> Any:
    asked = {"name": name, "size": len(body), "mime": mime, "purpose": "chat_attachment"}
    ticket = (await c.post("/v1/files/uploads", json=asked, headers=OPS)).json()["data"]
    put = await c.put(ticket["uploadUrl"], content=body, headers={**OPS, **ticket["headers"]})
    assert put.status_code == 204, put.text
    return ticket


async def test_a_chat_attachment_documents_service_cannot_read_is_refused(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    async with _client(engine, tenant, tmp_path) as c:
        png = await _put(c, PNG, "screenshot.png", "image/png")
        refused = await c.post(f"/v1/files/uploads/{png['fileId']}/complete", headers=OPS)
        assert refused.status_code == 415 and "pdf" in refused.json()["error"]["message"], refused.text
        pdf = await _put(c, PDF, "statement.pdf", "application/pdf")
        done = await c.post(f"/v1/files/uploads/{pdf['fileId']}/complete", headers=OPS)
        assert done.status_code == 200, done.text


async def test_a_chat_attachment_over_ten_megabytes_is_refused_at_the_ticket(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    async with _client(engine, tenant, tmp_path) as c:
        asked = {
            "name": "big.pdf",
            "size": 10 * 1024 * 1024 + 1,
            "mime": "application/pdf",
            "purpose": "chat_attachment",
        }
        refused = await c.post("/v1/files/uploads", json=asked, headers=OPS)
        assert refused.status_code == 413, refused.text
        limits = (await c.get("/v1/files/limits", headers=OPS)).json()["data"]["perPurpose"]
        assert {"purpose": "chat_attachment", "maxSizeMb": 10}.items() <= limits[0].items(), limits
