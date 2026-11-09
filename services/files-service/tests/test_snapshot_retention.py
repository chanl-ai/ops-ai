# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Knowledge snapshots, by failure mode: a snapshot that expires while its source still holds that version, one let
go that never starts counting down, and one past its days that is never deleted (or deleted while in use again)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import httpx

from ops_files.__main__ import RETENTION_CLASSES
from ops_files.app import create_files_app
from ops_files.service import FilesConfig
from ops_files.store import AsyncEngine, FilesStore
from ops_files.tenant_files import TenantFiles
from ops_files_client import FilesClient
from ops_identity import Auth, ServiceClient, dev_service_signer
from ops_service_kit.settings import Settings
from ops_storage.local import LocalObjectStore

PAGE = b"<html><body><h1>Late claims</h1><p>Tell us within 30 days.</p></body></html>"


async def test_a_snapshot_counts_its_30_days_from_release_not_from_upload(
    engine: AsyncEngine, tmp_path: Path, tenant: str
) -> None:
    config = FilesConfig(retention_classes=RETENTION_CLASSES, default_retention_class="standard")
    files = TenantFiles(
        LocalObjectStore(tmp_path / "o", signing_key=b"k" * 32), FilesStore(engine), config, scanning="off"
    )
    auth = Auth.for_dev(Settings(), audience="files", name="dev", email="dev@harborpine.example", tenant_id=tenant)
    app = create_files_app(files, engine=engine, auth=auth)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://files")
    client = FilesClient(
        ServiceClient(http, dev_service_signer(), "kb", "files", ["files:view", "files:create", "files:edit"])
    )

    async def kept_until() -> str | None:
        r = await http.get(f"/v1/files/{file_id}", headers={"X-Team-Id": "team_ops"})
        retention = r.json()["data"]["retention"]
        assert retention["classId"] == "knowledge-snapshot", retention
        return retention.get("deleteAfter")

    stored = await client.write(
        tenant, "team_ops", PAGE, name="late.html", mime="text/html", purpose="knowledge_snapshot", uploaded_by="kb"
    )
    file_id = stored.file.id
    await client.attach(tenant, "team_ops", file_id, type="source", ref_id="src_web", name="Claims help")
    assert await kept_until() is None, "kept with no end date while the source holds it"
    await client.detach(tenant, "team_ops", file_id, type="source", ref_id="src_web")
    assert await kept_until() == (date.today() + timedelta(days=30)).isoformat()
    await client.attach(tenant, "team_ops", file_id, type="source", ref_id="src_web", name="Claims help")
    assert await kept_until() is None, "taken back into use, the count stops"
    assert await files.purge_released(date.today() + timedelta(days=60)) == 0, "a snapshot in use is never purged"
    await client.detach(tenant, "team_ops", file_id, type="source", ref_id="src_web")
    assert await files.purge_released(date.today() + timedelta(days=29)) == 0
    assert await files.purge_released(date.today() + timedelta(days=31)) == 1
    gone = await http.get(f"/v1/files/{file_id}", headers={"X-Team-Id": "team_ops"})
    assert gone.status_code == 404, gone.text
    await client.aclose()
