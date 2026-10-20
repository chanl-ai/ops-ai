# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""documents-service for services (c-256): extract a file and read a document type, each call in the tenant and team
the caller acts for, which documents-service reads from the signed token, never from a query parameter."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from ops_identity import ServiceCallError, ServiceClient
from ops_service_kit.settings import Settings

__all__ = ["DocumentNotFound", "DocumentsClient", "DocumentsRefused"]


class DocumentsRefused(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


class DocumentNotFound(DocumentsRefused):
    """The file or the document type is not the caller's team's."""


def _refused(e: ServiceCallError) -> DocumentsRefused:
    code, message = e.code or "error", str(e)
    return DocumentNotFound(404, code, message) if e.status == 404 else DocumentsRefused(e.status, code, message)


class DocumentsClient:
    def __init__(self, documents: ServiceClient) -> None:
        self._documents = documents

    @classmethod
    def from_settings(
        cls, settings: Settings, *, service: str, timeout: float = 30, scopes: list[str] | None = None
    ) -> DocumentsClient:
        """documents-service at `settings.documents_url`, or the local port, with this service's signing key; `scopes`
        are the `documents:<action>` grants the token claims, `documents:view` and `documents:run` unless given."""
        base = settings.documents_url or f"http://127.0.0.1:{settings.documents_port}"
        return cls(
            ServiceClient.for_settings(
                settings,
                httpx.AsyncClient(base_url=base, timeout=timeout),
                service=service,
                audience="documents",
                scopes=scopes if scopes is not None else ["documents:view", "documents:run"],
                timeout=timeout,
            )
        )

    async def extract(
        self,
        tenant: str,
        team: str,
        file_id: str,
        request: dict[str, Any],
        *,
        idempotency_key: str,
        poll_seconds: float = 2.0,
        wait_seconds: float = 900.0,
    ) -> dict[str, Any]:
        """The file's extraction, finished: done, unreadable or failed. A small file is answered at once; a larger one
        is polled while queued or running. A retry with the same `idempotency_key` reads the same extraction."""
        try:
            answer: dict[str, Any] = await self._documents.request(
                "POST",
                "/v1/documents/extractions",
                json={"fileId": file_id, **request},
                headers={"Idempotency-Key": idempotency_key},
                tenant=tenant,
                team=team,
                timeout=180,  # parsing, OCR and the model call happen inside a synchronous answer
            )
            deadline = time.monotonic() + wait_seconds
            while answer["status"] in ("queued", "running"):
                if time.monotonic() > deadline:
                    raise DocumentsRefused(
                        504, "extraction_timeout", f"extraction {answer['id']} is still {answer['status']}"
                    )
                await asyncio.sleep(poll_seconds)
                answer = await self._documents.request(
                    "GET", f"/v1/documents/extractions/{answer['id']}", tenant=tenant, team=team
                )
        except ServiceCallError as e:
            raise _refused(e) from e
        return answer

    async def document_type(self, tenant: str, team: str, type_id: str) -> dict[str, Any]:
        """The team's document type with its versions; another team's or an unknown one is DocumentNotFound."""
        try:
            found: dict[str, Any] = await self._documents.request(
                "GET", f"/v1/document-types/{type_id}", tenant=tenant, team=team
            )
        except ServiceCallError as e:
            raise _refused(e) from e
        return found

    async def purge(self, tenant: str, team: str, file_id: str) -> dict[str, Any]:
        """Removes what documents-service read from a deleted file: {extractions, samples}; needs `documents:delete`."""
        try:
            done: dict[str, Any] = await self._documents.request(
                "POST", "/v1/documents/purge", json={"fileId": file_id}, tenant=tenant, team=team
            )
        except ServiceCallError as e:
            raise _refused(e) from e
        return done

    async def aclose(self) -> None:
        await self._documents.http.aclose()
