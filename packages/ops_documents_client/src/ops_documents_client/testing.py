"""documents-service's full-text read as services call it through DocumentsClient, faked with httpx MockTransport so a
service's tests never boot documents-service. It keeps what the real read promises: one read per Idempotency-Key (the
key with another request is 409), a file with no text ends `unreadable`, and a file over the synchronous size answers
202 and finishes after `polls` polls."""

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
    # Each file's pages of text, by file id; a file missing here has no text layer and reads as unreadable.
    pages: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    # Polls a read takes before it finishes, standing in for a file read in the background.
    polls: int = 0
    # A refusal every read answers with, standing in for a file documents-service cannot parse.
    refuse: tuple[int, str, str] | None = None
    keys: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    reads: int = 0
    _running: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])

    def _answer(self, extraction_id: str, file_id: str) -> dict[str, Any]:
        texts = self.pages.get(file_id)
        if not texts:
            return {"id": extraction_id, "status": "unreadable", "outcome": "unreadable", "fileId": file_id}
        pages: list[dict[str, Any]] = [{"number": n, "text": t, "tables": []} for n, t in enumerate(texts, 1)]
        text = "\n\n".join(texts)
        return {"id": extraction_id, "status": "done", "outcome": "ok", "fileId": file_id, "text": text, "pages": pages}

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.refuse is not None:
            return _error(*self.refuse)
        path = request.url.path
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
