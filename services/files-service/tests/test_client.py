# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""ops_files_client against the real files-service app in-process: what another service sees through it."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ops_files.app import create_files_app
from ops_files.store import AsyncEngine, FilesStore
from ops_files.tenant_files import TenantFiles
from ops_files_client import FileNotFound, FileNotReady, FilesClient
from ops_identity import Auth, ServiceClient, dev_service_signer
from ops_service_kit.settings import Settings
from ops_storage.local import LocalObjectStore
from tests.test_api import CONFIG, PDF


def _client(
    engine: AsyncEngine, tmp_path: Path, tenant: str, *, service: str = "kb", scopes: list[str] | None = None
) -> FilesClient:
    files = TenantFiles(
        LocalObjectStore(tmp_path / "objects", signing_key=b"k" * 32), FilesStore(engine), CONFIG, scanning="hook"
    )
    auth = Auth.for_dev(Settings(), audience="files", name="dev", email="dev@northfieldbank.com", tenant_id=tenant)
    app = create_files_app(files, engine=engine, auth=auth)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://files")
    granted = scopes if scopes is not None else ["files:view", "files:create", "files:edit"]
    return FilesClient(ServiceClient(http, dev_service_signer(), service, "files", granted))


async def test_a_service_stores_reads_and_references_a_file(engine: AsyncEngine, tmp_path: Path, tenant: str) -> None:
    files = _client(engine, tmp_path, tenant)
    stored = await files.write(
        tenant, "team_ops", PDF, name="a.pdf", mime="application/pdf", purpose="chat_attachment", uploaded_by="james"
    )
    file_id = stored.file.id
    assert stored.file.scan.status == "pending"
    with pytest.raises(FileNotReady):
        await files.read(tenant, "team_ops", file_id)
    with pytest.raises(FileNotReady):
        await files.attach(tenant, "team_ops", file_id, type="chat", ref_id="msg_1", name="Chat message")
    scanner = _client(engine, tmp_path, tenant, service="scanner", scopes=["files:decide"])
    await scanner.report_scan(tenant, file_id, status="clean", engine="clamav")
    assert await files.read(tenant, "team_ops", file_id) == PDF
    attached = await files.attach(tenant, "team_ops", file_id, type="chat", ref_id="msg_1", name="Chat message")
    assert attached.reference_count == 1
    assert (await files.detach(tenant, "team_ops", file_id, type="chat", ref_id="msg_1")).reference_count == 0
    again = await files.write(
        tenant, "team_ops", PDF, name="b.pdf", mime="application/pdf", purpose="chat_attachment", uploaded_by="maya"
    )
    assert again.deduplicated and again.file.id == file_id
    await files.aclose()


async def test_another_teams_or_tenants_file_is_not_found(engine: AsyncEngine, tmp_path: Path, tenant: str) -> None:
    files = _client(engine, tmp_path, tenant)
    stored = await files.write(
        tenant, "team_ops", PDF, name="a.pdf", mime="application/pdf", purpose="export", uploaded_by="james"
    )
    with pytest.raises(FileNotFound):
        await files.get(tenant, "team_security", stored.file.id)
    with pytest.raises(FileNotFound):
        await files.get(f"{tenant}_other", "team_ops", stored.file.id)
    await files.aclose()
