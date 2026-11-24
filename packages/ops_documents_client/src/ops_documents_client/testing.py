"""documents-service's readings and extractions as services call them through DocumentsClient, faked with httpx
MockTransport so a service's tests never boot documents-service. It keeps what the real service promises: one reading
per file and OCR choice, a file with no text read with its page listed as unread, a file read in the background
answering 202 and finishing after `polls` polls, and one extraction per Idempotency-Key (the key with another request
is 409)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TypedDict

import httpx

from ops_documents_client import DocumentsClient
from ops_identity import ServiceClient, dev_service_signer
from ops_service_kit.http import Json, JsonList, PageJSON


def _error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"success": False, "error": {"code": code, "message": message}})


class FakeType(TypedDict):
    """A document type as the list answers it."""

    id: str
    name: str
    description: str | None
    latestVersion: int


class FakeTypesPage(TypedDict):
    data: list[FakeType]
    pagination: PageJSON
    facets: dict[str, dict[str, int]]


class HeldExtraction(TypedDict):
    """An extraction asked for under one Idempotency-Key: the request it was asked with and the polls it has left."""

    request: Json
    id: str
    polls: int


@dataclass
class FakeDocumentsService:
    # Each file's pages of text, by file id; a file missing here has no text, even by OCR.
    pages: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    # Polls a reading or an extraction takes before it finishes, standing in for a file read in the background.
    polls: int = 0
    # A refusal every call answers with, standing in for a file documents-service cannot read.
    refuse: tuple[int, str, str] | None = None
    keys: dict[str, HeldExtraction] = field(default_factory=dict[str, HeldExtraction])
    # Readings made, by (file id, OCR mode); a second ask for the same pair reads nothing.
    readings: dict[tuple[str, str], int] = field(default_factory=dict[tuple[str, str], int])
    reads: int = 0
    # The team's document types, answered a page of `type_page_size` at a time as the real list is.
    types: list[FakeType] = field(default_factory=list[FakeType])
    type_page_size: int = 20
    # Files whose read the model gave no answer for, by file id, with the reason: cut_off, empty, declined or filtered.
    no_answer: dict[str, str] = field(default_factory=dict[str, str])
    _running: dict[str, HeldExtraction] = field(default_factory=dict[str, HeldExtraction])
    # Each batch of typed values saved (POST .../corrections), with the extraction it was saved on.
    corrected: list[Json] = field(default_factory=list[Json])

    def _reading(self, file_id: str, ocr: str) -> Json:
        texts = self.pages.get(file_id)
        pages: JsonList
        if not texts:
            pages = [{"number": 1, "source": "none", "text": "", "unreadReason": "no text found, even by OCR"}]
        else:
            pages = [{"number": n, "source": "text", "text": t} for n, t in enumerate(texts, 1)]
        return {
            "fileId": file_id,
            "digest": f"dig_{file_id}",
            "status": "done",
            "readerVersion": "reading-1",
            "settings": {"ocr": ocr, "language": "eng"},
            "pagesTotal": len(pages),
            "pagesDone": len(pages),
            "pages": pages,
        }

    def _pending(self, file_id: str, ocr: str) -> Json:
        return {**self._reading(file_id, ocr), "status": "reading", "pagesDone": 0, "pages": None}

    def _answer(self, extraction_id: str, file_id: str) -> Json:
        texts = self.pages.get(file_id)
        if not texts:
            return {"id": extraction_id, "status": "unreadable", "outcome": "unreadable", "fileId": file_id}
        if file_id in self.no_answer:
            said: Json = {"reason": self.no_answer[file_id], "step": "extract", "tries": 1}
            return {
                "id": extraction_id,
                "status": "done",
                "outcome": "incomplete",
                "fileId": file_id,
                "incomplete": said,
            }
        return {"id": extraction_id, "status": "done", "outcome": "ok", "fileId": file_id}

    def _types_page(self, page: int) -> FakeTypesPage:
        size, total = self.type_page_size, len(self.types)
        pages = max(1, -(-total // size))
        window = PageJSON(
            page=page, pageSize=size, total=total, totalPages=pages, hasNext=page < pages, hasPrev=page > 1
        )
        return FakeTypesPage(data=self.types[(page - 1) * size : page * size], pagination=window, facets={})

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.refuse is not None:
            return _error(*self.refuse)
        path = request.url.path
        if request.method == "GET" and path == "/v1/document-types":
            return httpx.Response(200, json={"data": self._types_page(int(request.url.params.get("page", "1")))})
        if request.method == "POST" and path == "/v1/documents/readings":
            body = json.loads(request.content)
            asked = (str(body["fileId"]), str(body.get("ocr") or "auto"))
            left = self.readings.setdefault(asked, self.polls)
            if left:
                return httpx.Response(202, json={"data": self._pending(*asked)})
            return httpx.Response(200, json={"data": self._reading(*asked)})
        if request.method == "GET" and path.startswith("/v1/documents/readings/"):
            asked = (path.rsplit("/", 1)[-1], request.url.params.get("ocr", "auto"))
            if asked not in self.readings:
                return httpx.Response(200, json={"data": {**self._pending(*asked), "status": "none"}})
            self.readings[asked] = max(0, self.readings[asked] - 1)
            if self.readings[asked]:
                return httpx.Response(200, json={"data": self._pending(*asked)})
            return httpx.Response(200, json={"data": self._reading(*asked)})
        if request.method == "POST" and path == "/v1/documents/extractions":
            body = json.loads(request.content)
            key = request.headers["Idempotency-Key"]
            if key in self.keys and self.keys[key]["request"] != body:
                return _error(409, "idempotency_conflict", "the key was used for another request")
            if key not in self.keys:
                self.reads += 1
                self.keys[key] = {"request": body, "id": f"ext_{self.reads}", "polls": self.polls}
            held = self.keys[key]
            if held["polls"]:
                self._running[held["id"]] = held
                return httpx.Response(202, json={"data": {"id": held["id"], "status": "running"}})
            return httpx.Response(200, json={"data": self._answer(held["id"], body["fileId"])})
        if request.method == "POST" and path.startswith("/v1/documents/extractions/") and path.endswith("/corrections"):
            body = json.loads(request.content)
            extraction_id = path.split("/")[-2]
            self.corrected.append({"extractionId": extraction_id, **body})
            return httpx.Response(200, json={"data": {"id": extraction_id, "status": "done"}})
        if request.method == "GET" and path.startswith("/v1/documents/extractions/"):
            held = self._running.get(path.rsplit("/", 1)[-1])
            if held is None:
                return _error(404, "not_found", "no such extraction")
            held["polls"] -= 1
            if held["polls"] > 0:
                return httpx.Response(200, json={"data": {"id": held["id"], "status": "running"}})
            return httpx.Response(200, json={"data": self._answer(held["id"], str(held["request"]["fileId"]))})
        return _error(404, "no_route", f"{request.method} {path} is not faked")

    def client(self, *, service: str = "agents") -> DocumentsClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.handle), base_url="http://documents")
        return DocumentsClient(ServiceClient(http, dev_service_signer(), service, "documents", ["documents:run"]))
