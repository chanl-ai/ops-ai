# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""When a download holds the database, by failure mode: the file's bytes read from storage, or sent to the caller,
while the request's transaction is still open, so every slow download holds a pooled connection for as long as the
caller takes to read it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from ops_files.app import create_files_app
from ops_files.store import FilesStore, engine_for
from ops_files.tenant_files import TenantFiles
from ops_identity import Auth
from ops_service_kit.contract import response_checker
from ops_service_kit.request_timing import RequestTiming, current
from ops_service_kit.settings import Settings
from ops_storage.base import PresignedRequest, StorageBackend
from ops_storage.local import LocalObjectStore

from .test_api import CONFIG, OPS, PDF, sign_in


class _Noting(LocalObjectStore):
    """The local backend, noting at each chunk it reads how many transactions the request holds open."""

    open_at_chunk: list[int]
    # The request's timing, read once the answer is sent: how many transactions it ran in all.
    timing: RequestTiming | None = None

    def open_read(self, key: str, *, chunk_size: int = 1 << 20) -> AsyncIterator[bytes]:
        chunks = super().open_read(key, chunk_size=chunk_size)

        async def noted() -> AsyncIterator[bytes]:
            async for chunk in chunks:
                timing = current()
                self.timing = timing
                self.open_at_chunk.append(timing.db_tx_open if timing is not None else -1)
                yield chunk

        return noted()


async def test_the_content_is_read_and_sent_with_no_transaction_open(
    database_url: str, tenant: str, tmp_path: Path
) -> None:
    # The service's own engine, whose transactions the request line counts; the suite's plain engine is not counted.
    engine = engine_for(database_url)
    store = _Noting(tmp_path / "objects", signing_key=b"k" * 32)
    store.open_at_chunk = []
    files = TenantFiles(store, FilesStore(engine), CONFIG, scanning="off")
    auth = Auth.for_dev(Settings(), audience="files", name="james", email="james@harborpine.example", tenant_id=tenant)
    app = create_files_app(files, engine=engine, auth=auth)
    sign_in(app, tenant, "builder")
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://files", event_hooks=hooks
    ) as c:
        ask = {"name": "s.pdf", "size": len(PDF), "mime": "application/pdf", "purpose": "chat_attachment"}
        ticket = (await c.post("/v1/files/uploads", json=ask, headers=OPS)).json()["data"]
        put = await c.put(ticket["uploadUrl"], content=PDF, headers={**OPS, **ticket["headers"]})
        assert put.status_code == 204, put.text
        done = await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS)
        assert done.status_code == 200, done.text
        store.open_at_chunk.clear()
        r = await c.get(f"/v1/files/{ticket['fileId']}/content", headers=OPS)
    await engine.dispose()
    assert (r.status_code, r.content) == (200, PDF), r.text
    assert store.open_at_chunk, "the download read the stored bytes"
    assert set(store.open_at_chunk) == {0}, f"a chunk was read with a transaction open: {store.open_at_chunk}"
    assert store.timing is not None and store.timing.db_tx == 1, "the file's rows are read in one transaction"


class _Signing(LocalObjectStore):
    """A backend that signs URLs (as S3 and Azure do), noting how many transactions the request holds open at each
    signature: on Azure with an expired delegation key a signature is a network call."""

    open_at_sign: list[int]

    @property
    def backend(self) -> StorageBackend:
        return "s3"

    def _note(self) -> None:
        timing = current()
        self.open_at_sign.append(timing.db_tx_open if timing is not None else -1)

    def presign_put(self, key: str, *, content_type: str, max_bytes: int, expires_in: int) -> PresignedRequest:
        self._note()
        return super().presign_put(key, content_type=content_type, max_bytes=max_bytes, expires_in=expires_in)

    def presign_get(self, key: str, *, expires_in: int, filename: str) -> str:
        self._note()
        return super().presign_get(key, expires_in=expires_in, filename=filename)


async def test_upload_and_download_links_are_signed_with_no_transaction_open(
    database_url: str, tenant: str, tmp_path: Path
) -> None:
    engine = engine_for(database_url)
    store = _Signing(tmp_path / "objects", signing_key=b"k" * 32)
    store.open_at_sign = []
    files = TenantFiles(store, FilesStore(engine), CONFIG, scanning="off")
    auth = Auth.for_dev(Settings(), audience="files", name="james", email="james@harborpine.example", tenant_id=tenant)
    app = create_files_app(files, engine=engine, auth=auth)
    sign_in(app, tenant, "builder")
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://files", event_hooks=hooks
    ) as c:
        ask = {"name": "s.pdf", "size": len(PDF), "mime": "application/pdf", "purpose": "chat_attachment"}
        # With a key the ticket reads a row (the key's claim) before it signs.
        ticket = await c.post("/v1/files/uploads", json=ask, headers={**OPS, "Idempotency-Key": "sign-once"})
        assert ticket.status_code == 201, ticket.text
        written = await c.post(
            "/v1/files",
            params={"name": "w.pdf", "purpose": "chat_attachment"},
            content=PDF,
            headers={**OPS, "Content-Type": "application/pdf"},
        )
        assert written.status_code == 201, written.text
        link = await c.post(f"/v1/files/{written.json()['data']['file']['id']}/download-url", json={}, headers=OPS)
        assert link.status_code == 200, link.text
    await engine.dispose()
    assert len(store.open_at_sign) == 3, "the ticket, the one-request write and the download link each sign"
    assert store.open_at_sign == [0, 0, 0], f"a URL was signed with a transaction open: {store.open_at_sign}"
