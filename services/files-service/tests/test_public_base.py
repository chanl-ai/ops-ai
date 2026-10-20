"""files-service behind a proxy that serves it under a path (c-215): the proxy strips the prefix, so the request's own
base lacks it, and an upload or download URL built on that base misses the service. Every URL it hands out is built
on `files_public_url` when set."""

from __future__ import annotations

import pytest

from .test_api import (  # pyright: ignore[reportPrivateUsage]
    OPS,
    PDF,
    Client,
    _data,  # pyright: ignore[reportPrivateUsage]
    client,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)

BASE = "https://ops.test/api/files"


async def test_upload_and_download_urls_are_built_on_the_public_base(
    client: Client,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPS_FILES_PUBLIC_URL", f"{BASE}/")
    async with client() as c:
        body = {"name": "s.pdf", "size": len(PDF), "mime": "application/pdf", "purpose": "chat_attachment"}
        ticket = _data(await c.post("/v1/files/uploads", json=body, headers=OPS))
        assert ticket["uploadUrl"] == f"{BASE}/v1/files/uploads/{ticket['fileId']}/content", ticket
        # The proxy strips its prefix before the request reaches the service.
        path = ticket["uploadUrl"].removeprefix(BASE)
        put = await c.put(path, content=PDF, headers={**OPS, **ticket["headers"]})
        assert put.status_code == 204, put.text
        done = _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))
        link = _data(await c.post(f"/v1/files/{done['file']['id']}/download-url", headers=OPS))
        assert link["url"] == f"{BASE}/v1/files/{done['file']['id']}/content", link
