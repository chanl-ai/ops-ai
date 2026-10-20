# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The files-service client for other services: file ids in, bytes and metadata out, over `/v1/files`.

Every call names the tenant (in the service token) and the team the caller acts for; files-service answers 404 for a
file of another tenant or team, so a caller holding a stray id learns nothing. A hand-written client until clients
are generated from each service's openapi.json (service host and deployment, open question 3).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal, cast

import httpx
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ops_identity import ServiceCallError, ServiceClient
from ops_service_kit.settings import Settings

__all__ = [
    "FileInfo",
    "FileNotFound",
    "FileNotReady",
    "FileScan",
    "FilesClient",
    "FilesRefused",
    "StoredFile",
]

ReferenceType = Literal["source", "case", "chat", "eval_set", "test_set", "evidence", "export", "tool_module"]
Purpose = Literal[
    "knowledge_source",
    "chat_attachment",
    "case_attachment",
    "document_type_sample",
    "email_body",
    "test_import",
    "evidence_bundle",
    "export",
    "tool_spec",
    "avatar",
]


class _In(BaseModel):
    # Fields files-service adds later are ignored, so a newer service never breaks an older caller.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class FileScan(_In):
    status: Literal["pending", "clean", "infected", "failed"]
    engine: str | None = None
    detail: str | None = None


class FileInfo(_In):
    id: str
    name: str
    mime: str
    size: int
    digest: str
    purpose: str
    team: str
    uploaded_by: str
    scan: FileScan
    reference_count: int = 0


class StoredFile(_In):
    file: FileInfo
    deduplicated: bool


class FilesRefused(Exception):
    """files-service refused the call; `status` and `code` are its answer."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class FileNotFound(FilesRefused):
    """No such file in this tenant and team."""


class FileNotReady(FilesRefused):
    """The file is not scanned clean (pending, infected or failed), or its state forbids the change."""


def _raise_for(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        error: dict[str, Any] = response.json().get("error") or {}
    except ValueError:
        error = {}
    code, message = str(error.get("code", "error")), str(error.get("message", response.text[:200]))
    if response.status_code == 404:
        raise FileNotFound(404, code, message)
    if response.status_code in (409, 423):
        raise FileNotReady(response.status_code, code, message)
    raise FilesRefused(response.status_code, code, message)


def _refused(e: ServiceCallError) -> FilesRefused:
    code, message = e.code or "error", str(e)
    if e.status == 404:
        return FileNotFound(404, code, message)
    if e.status in (409, 423):
        return FileNotReady(e.status, code, message)
    return FilesRefused(e.status, code, message)


class FilesClient:
    def __init__(self, files: ServiceClient) -> None:
        """`files` calls files-service as this service; each call names the tenant and the team it acts in, which
        files-service reads from the token instead of any query parameter (c-168). JSON calls go through it; an upload
        and a download send bytes on its connection with its token."""
        self._files = files

    @classmethod
    def from_settings(
        cls, settings: Settings, *, service: str, timeout: float = 30, scopes: list[str] | None = None
    ) -> FilesClient:
        """files-service at `settings.files_url`, or the local port, with this service's signing key. `scopes` are
        the `area:action` grants the token claims, `files:view`, `files:create` and `files:edit` unless given; a scanner
        claims `files:decide` for `report_scan`. files-service accepts only the scopes its Settings.service_scopes
        gives the calling service."""
        base = settings.files_url or f"http://127.0.0.1:{settings.files_port}"
        return cls(
            ServiceClient.for_settings(
                settings,
                httpx.AsyncClient(base_url=base, timeout=timeout),
                service=service,
                audience="files",
                scopes=scopes if scopes is not None else ["files:view", "files:create", "files:edit"],
                timeout=timeout,
            )
        )

    async def _json(self, method: str, path: str, tenant: str, team: str | None, **kw: Any) -> FileInfo:
        try:
            data = await self._files.request(method, path, tenant=tenant, team=team, **kw)
        except ServiceCallError as e:
            raise _refused(e) from e
        return FileInfo.model_validate(data)

    async def write(
        self,
        tenant: str,
        team: str,
        data: bytes,
        *,
        name: str,
        mime: str,
        purpose: Purpose,
        uploaded_by: str,
        idempotency_key: str | None = None,
    ) -> StoredFile:
        """Stores `data` as a new file of `team`, or returns the team's file with the same bytes (`deduplicated`).
        A retry with the same `idempotency_key` returns the file the first call stored."""
        params = {"name": name, "purpose": purpose, "uploadedBy": uploaded_by}
        headers = {**self._files.headers(tenant=tenant, team=team), "Content-Type": mime}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        response = await self._files.http.post("/v1/files", params=params, content=data, headers=headers)
        _raise_for(response)
        return StoredFile.model_validate(response.json()["data"])

    async def get(self, tenant: str, team: str, file_id: str) -> FileInfo:
        return await self._json("GET", f"/v1/files/{file_id}", tenant, team)

    async def stream(self, tenant: str, team: str, file_id: str) -> AsyncIterator[bytes]:
        """A clean file's bytes as they arrive; raises `FileNotReady` before the first byte when it is not clean."""
        http = self._files.http
        headers = self._files.headers(tenant=tenant, team=team)
        request = http.build_request("GET", f"/v1/files/{file_id}/content", headers=headers)
        response = await http.send(request, stream=True)
        try:
            if not response.is_success:
                await response.aread()
                _raise_for(response)
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()

    async def read(self, tenant: str, team: str, file_id: str) -> bytes:
        return b"".join([chunk async for chunk in self.stream(tenant, team, file_id)])

    async def attach(
        self,
        tenant: str,
        team: str,
        file_id: str,
        *,
        type: ReferenceType,
        ref_id: str,
        name: str,
        href: str | None = None,
    ) -> FileInfo:
        """Records that `ref_id` uses the file; `FileNotReady` when the file is not scanned clean (files 5.3.4)."""
        body = {"type": type, "refId": ref_id, "name": name, "href": href}
        return await self._json("POST", f"/v1/files/{file_id}/references", tenant, team, json=body)

    async def set_data(self, tenant: str, team: str, file_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Records what was read from the file (c-250); needs `files:edit`. Answers the stored data."""
        try:
            detail = await self._files.request("PUT", f"/v1/files/{file_id}/data", json=data, tenant=tenant, team=team)
        except ServiceCallError as e:
            raise _refused(e) from e
        return cast(dict[str, Any], cast(dict[str, Any], detail).get("data") or {})

    async def detach(self, tenant: str, team: str, file_id: str, *, type: ReferenceType, ref_id: str) -> FileInfo:
        return await self._json("DELETE", f"/v1/files/{file_id}/references/{type}/{ref_id}", tenant, team)

    async def report_scan(
        self,
        tenant: str,
        file_id: str,
        *,
        status: Literal["clean", "infected", "failed"],
        engine: str,
        detail: str | None = None,
    ) -> FileInfo:
        """A scanner adapter's verdict, through the scan hook; the token needs `files:decide`."""
        body = {"fileId": file_id, "status": status, "engine": engine, "detail": detail}
        return await self._json("POST", "/v1/files/scan-results", tenant, None, json=body)

    async def aclose(self) -> None:
        await self._files.http.aclose()
