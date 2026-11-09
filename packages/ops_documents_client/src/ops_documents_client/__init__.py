# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""documents-service for services: extract a file and read a document type, each call in the tenant and team
the caller acts for, which documents-service reads from the signed token, never from a query parameter."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx

from ops_identity import ServiceCallError, ServiceClient, segment
from ops_service_kit.settings import Settings

__all__ = ["READING", "READING_PENDING", "DocumentNotFound", "DocumentsClient", "DocumentsRefused", "reading_text"]

# An extraction in these states has not finished: a file over documents-service's synchronous size reads in the
# background.
READING = ("queued", "running")
# A reading in these states has not finished: a scan or a long file is read in the background.
READING_PENDING = ("queued", "reading")


def reading_text(reading: dict[str, Any]) -> str:
    """A finished reading's text, page after page."""
    pages = cast(list[dict[str, Any]], reading.get("pages") or [])
    return "\n\n".join(str(p.get("text") or "") for p in pages if p.get("text"))


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
    ) -> dict[str, Any]:
        """The file's extraction: finished (done, unreadable or failed) for a small file, which is read at once, or
        queued or running for a larger one, read in the background; documents-service reports `extraction.finished`
        when it ends. A repeat with the same `idempotency_key` answers the same extraction as it is now."""
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
        except ServiceCallError as e:
            raise _refused(e) from e
        return answer

    async def reading(
        self,
        tenant: str,
        team: str,
        file_id: str,
        *,
        ocr: str = "auto",
        wait_s: float = 0.0,
        poll_s: float = 1.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> dict[str, Any]:
        """The file's reading: every page's text in reading order, with how each page was read, its blocks, words,
        form fields and OCR quality. Keyed by the file's bytes and the OCR settings, so every caller of the same file
        (a knowledge base, a chat attachment, an agent's read_file) gets the one reading already made. A reading made
        in the background is waited for up to `wait_s`; the answer is then the reading as it is, still `queued` or
        `reading` when it took longer, and documents-service reports `reading.finished` when it ends."""
        try:
            answer: dict[str, Any] = await self._documents.request(
                "POST",
                "/v1/documents/readings",
                json={"fileId": file_id, "ocr": ocr},
                tenant=tenant,
                team=team,
                timeout=180,  # a small file is read inside the answer
            )
            ends = time.monotonic() + wait_s
            while answer.get("status") in READING_PENDING and time.monotonic() < ends:
                await sleep(poll_s)
                answer = await self._documents.request(
                    "GET", f"/v1/documents/readings/{segment(file_id)}", params={"ocr": ocr}, tenant=tenant, team=team
                )
        except ServiceCallError as e:
            raise _refused(e) from e
        return answer

    async def document_type(self, tenant: str, team: str, type_id: str) -> dict[str, Any]:
        """The team's document type with its versions; another team's or an unknown one is DocumentNotFound."""
        try:
            found: dict[str, Any] = await self._documents.request(
                "GET", f"/v1/document-types/{segment(type_id)}", tenant=tenant, team=team
            )
        except ServiceCallError as e:
            raise _refused(e) from e
        return found

    async def document_types(self, tenant: str, team: str) -> list[dict[str, Any]]:
        """The team's document types (their newest versions), for finding one by name."""
        try:
            listed: dict[str, Any] = await self._documents.request(
                "GET", "/v1/document-types", tenant=tenant, team=team
            )
        except ServiceCallError as e:
            raise _refused(e) from e
        return list(listed.get("items") or [])

    async def template_copies(self, tenant: str, team: str) -> list[dict[str, Any]]:
        """The document types the team's apps bring, each with its state for the team and the team's copy."""
        try:
            listed: list[dict[str, Any]] = await self._documents.request(
                "GET", "/v1/templates", tenant=tenant, team=team
            )
        except ServiceCallError as e:
            raise _refused(e) from e
        return listed

    async def extraction(self, tenant: str, team: str, extraction_id: str) -> dict[str, Any]:
        """An extraction as it is now: queued, running, or finished with its answer."""
        try:
            found: dict[str, Any] = await self._documents.request(
                "GET", f"/v1/documents/extractions/{segment(extraction_id)}", tenant=tenant, team=team
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
