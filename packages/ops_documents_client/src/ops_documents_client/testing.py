"""documents-service's readings and extractions as services call them through DocumentsClient, faked with httpx
MockTransport so a service's tests never boot documents-service. It keeps what the real service promises: one reading
per file and OCR choice, a file with no text read with its page listed as unread, a file read in the background
answering 202 and finishing after `polls` polls, and one extraction per Idempotency-Key (the key with another request
is 409)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from ops_documents_client import DocumentsClient
from ops_identity import ServiceClient, dev_service_signer


def _error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"success": False, "error": {"code": code, "message": message}})


@dataclass
class FakeDocumentsService:
    # Each file's pages of text, by file id; a file missing here has no text, even by OCR.
    pages: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    # Polls a reading or an extraction takes before it finishes, standing in for a file read in the background.
    polls: int = 0
    # A refusal every call answers with, standing in for a file documents-service cannot read.
    refuse: tuple[int, str, str] | None = None
    keys: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    # Readings made, by (file id, OCR mode); a second ask for the same pair reads nothing.
    readings: dict[tuple[str, str], int] = field(default_factory=dict[tuple[str, str], int])
    reads: int = 0
    _running: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])

    def _reading(self, file_id: str, ocr: str) -> dict[str, Any]:
        texts = self.pages.get(file_id)
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

    def _pending(self, file_id: str, ocr: str) -> dict[str, Any]:
        return {**self._reading(file_id, ocr), "status": "reading", "pagesDone": 0, "pages": None}

    def _answer(self, extraction_id: str, file_id: str) -> dict[str, Any]:
        texts = self.pages.get(file_id)
        if not texts:
            return {"id": extraction_id, "status": "unreadable", "outcome": "unreadable", "fileId": file_id}
        return {"id": extraction_id, "status": "done", "outcome": "ok", "fileId": file_id}

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.refuse is not None:
            return _error(*self.refuse)
        path = request.url.path
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
        if request.method == "GET" and path.startswith("/v1/documents/extractions/"):
            held = self._running.get(path.rsplit("/", 1)[-1])
            if held is None:
                return _error(404, "not_found", "no such extraction")
            held["polls"] -= 1
            if held["polls"] > 0:
                return httpx.Response(200, json={"data": {"id": held["id"], "status": "running"}})
            return httpx.Response(200, json={"data": self._answer(held["id"], held["request"]["fileId"])})
        return _error(404, "no_route", f"{request.method} {path} is not faked")

    def client(self, *, service: str = "agents") -> DocumentsClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.handle), base_url="http://documents")
        return DocumentsClient(ServiceClient(http, dev_service_signer(), service, "documents", ["documents:run"]))
