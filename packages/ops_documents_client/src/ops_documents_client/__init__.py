# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""documents-service for services: extract a file and read a document type, each call in the tenant and team
the caller acts for, which documents-service reads from the signed token, never from a query parameter."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any, TypedDict

import httpx

from ops_identity import ServiceCallError, ServiceClient, segment
from ops_service_kit.http import Json, JsonValue, PageJSON
from ops_service_kit.narrow import a_list, an_object
from ops_service_kit.settings import Settings

__all__ = ["READING", "READING_PENDING", "DocumentNotFound", "DocumentsClient", "DocumentsRefused", "reading_text"]


class _TypesPage(TypedDict):
    """One page of `GET /v1/document-types`, the shared list contract."""

    data: list[Json]
    pagination: PageJSON


# An extraction in these states has not finished: a file over documents-service's synchronous size reads in the
# background.
READING = ("queued", "running")
# A reading in these states has not finished: a scan or a long file is read in the background.
READING_PENDING = ("queued", "reading")


def reading_text(reading: Mapping[str, JsonValue]) -> str:
    """A finished reading's text, page after page. A reading with no pages has none; pages of another shape fail the
    read, as iterating them did."""
    pages = (
        [an_object(p, "a reading's page") for p in a_list(reading["pages"], "a reading's pages")]
        if reading.get("pages")
        else []
    )
    return "\n\n".join(str(p.get("text") or "") for p in pages if p.get("text"))


class DocumentsRefused(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


class DocumentNotFound(DocumentsRefused):
    """The file or the document type is not the caller's team's."""


def _id(value: str) -> str:
    """An id as one path segment; an id that cannot be one names nothing the team holds."""
    try:
        return segment(value)
    except ValueError:
        raise DocumentNotFound(404, "not_found", f"No {value!r}") from None


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
        """documents-service at the documents endpoint, with this service's signing key; `scopes`
        are the `documents:<action>` grants the token claims, `documents:view` and `documents:run` unless given."""
        base = settings.endpoint("documents").base
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
        request: Mapping[str, JsonValue],
        *,
        idempotency_key: str,
    ) -> Json:
        """The file's extraction: finished (done, unreadable or failed) for a small file, which is read at once, or
        queued or running for a larger one, read in the background; documents-service reports `extraction.finished`
        when it ends. A repeat with the same `idempotency_key` answers the same extraction as it is now."""
        try:
            answer = await self._documents.request(
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
            answer = await self._documents.request(
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
                    "GET", f"/v1/documents/readings/{_id(file_id)}", params={"ocr": ocr}, tenant=tenant, team=team
                )
        except ServiceCallError as e:
            raise _refused(e) from e
        return answer

    async def document_type(self, tenant: str, team: str, type_id: str) -> dict[str, Any]:
        """The team's document type with its versions; another team's or an unknown one is DocumentNotFound."""
        try:
            found = await self._documents.request("GET", f"/v1/document-types/{_id(type_id)}", tenant=tenant, team=team)
        except ServiceCallError as e:
            raise _refused(e) from e
        return found

    async def document_types(self, tenant: str, team: str) -> list[Json]:
        """Every one of the team's document types (their newest versions), for finding one by name: the list is
        paged, so each page is read until the last."""
        page = await self._types_page(tenant, team, 1)
        found = page["data"]
        while page["pagination"]["hasNext"]:
            page = await self._types_page(tenant, team, page["pagination"]["page"] + 1)
            found = [*found, *page["data"]]
        return found

    async def _types_page(self, tenant: str, team: str, page: int) -> _TypesPage:
        try:
            listed: _TypesPage = await self._documents.request(
                "GET", "/v1/document-types", params={"page": page}, tenant=tenant, team=team
            )
        except ServiceCallError as e:
            raise _refused(e) from e
        return listed

    async def template_copies(self, tenant: str, team: str) -> list[dict[str, Any]]:
        """The document types the team's apps bring, each with its state for the team and the team's copy: every page
        of the list."""
        rows: list[Json] = []
        page = 1
        while True:
            try:
                got = await self._documents.request(
                    "GET", "/v1/templates", tenant=tenant, team=team, params={"page": page, "pageSize": 50}
                )
            except ServiceCallError as e:
                raise _refused(e) from e
            rows += got["data"]
            if not got["pagination"]["hasNext"]:
                return rows
            page += 1

    async def extraction(self, tenant: str, team: str, extraction_id: str) -> Json:
        """An extraction as it is now: queued, running, or finished with its answer."""
        try:
            found = await self._documents.request(
                "GET", f"/v1/documents/extractions/{_id(extraction_id)}", tenant=tenant, team=team
            )
        except ServiceCallError as e:
            raise _refused(e) from e
        return found

    async def correct(
        self, tenant: str, team: str, extraction_id: str, corrections: list[Json], *, entered_by: str, checked: bool
    ) -> Json:
        """Saves the values a person typed ([{field, record?, value}]) on an extraction in one call, recorded as
        `entered_by`; documents-service normalises each by its field's type and skips unchanged ones. `checked`: the
        person checked the whole read. Claims `documents:edit`, which the calling service must hold."""
        body: dict[str, Any] = {"corrections": corrections, "enteredBy": entered_by, "checked": checked}
        # documents:edit is claimed on this call only, so the client's other calls never carry it.
        editing = replace(self._documents, scopes=[*self._documents.scopes, "documents:edit"])
        try:
            saved = await editing.request(
                "POST",
                f"/v1/documents/extractions/{_id(extraction_id)}/corrections",
                json=body,
                tenant=tenant,
                team=team,
            )
        except ServiceCallError as e:
            raise _refused(e) from e
        return saved

    async def purge(self, tenant: str, team: str, file_id: str) -> Json:
        """Removes what documents-service read from a deleted file: {extractions, samples}; needs `documents:delete`."""
        try:
            done = await self._documents.request(
                "POST", "/v1/documents/purge", json={"fileId": file_id}, tenant=tenant, team=team
            )
        except ServiceCallError as e:
            raise _refused(e) from e
        return done

    async def aclose(self) -> None:
        await self._documents.http.aclose()
