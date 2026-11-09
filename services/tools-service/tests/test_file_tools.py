"""The built-in Files and Document types tools, by failure mode: another team's file or type read, an
install not serving or showing them, a name matching several files read at random, a long file flooding the model, a
large file's read still running when the tool answers, a second read paying again, documents-service's refusal
reaching the agent as a crash, and a file the scan has not cleared. files-service is ops_files_client's fake;
documents-service is faked on the routes the tools call, refusing a reused key with a different request as it does
(409)."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from ops_documents_client import DocumentsClient
from ops_files_client.testing import FakeFilesService
from ops_identity import ServiceClient, dev_service_signer
from ops_tools.file_tools import TEXT_LIMIT, FileTools
from ops_tools.modules.seed import BUILT_IN
from ops_tools.registry import ToolRegistry

TENANT, OPS, RETAIL = "t_bank", "team_ops", "team_retail"
LEVY_ID = "dt_levy"
LEVY: dict[str, Any] = {"id": LEVY_ID, "name": "Levy notice", "fields": [{"key": "amount", "type": "number"}]}


def _team(request: httpx.Request) -> str:
    body = request.headers["Authorization"].removeprefix("Bearer ").split(".")[1]
    return str(json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))["team_id"])


@dataclass
class FakeDocuments:
    """documents-service as the tools call it: types per team, a file's reading, a fields read, and a large file whose
    reading or read runs in the background for `polls` polls."""

    texts: dict[str, str] = field(default_factory=dict[str, str])
    polls: int = 0
    refuse: tuple[int, str, str] | None = None
    asked: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    keys: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    reads: int = 0
    # The OCR mode each reading was asked with, and the readings made, by (file id, mode).
    ocr: list[str] = field(default_factory=list[str])
    readings: dict[tuple[str, str], int] = field(default_factory=dict[tuple[str, str], int])

    def _reading(self, file_id: str, status: str = "done") -> dict[str, Any]:
        text = self.texts.get(file_id, "")
        pages = [{"number": 1, "source": "text" if text else "none", "text": text}]
        return {"fileId": file_id, "status": status, **({"pages": pages} if status == "done" else {})}

    def handle(self, request: httpx.Request) -> httpx.Response:
        team, path = _team(request), request.url.path
        if self.refuse:
            status, code, message = self.refuse
            return httpx.Response(status, json={"success": False, "error": {"code": code, "message": message}})
        if path == "/v1/document-types":
            return httpx.Response(200, json={"data": {"items": [LEVY] if team == OPS else []}})
        if path.startswith("/v1/document-types/"):
            if team == OPS and path.endswith(LEVY_ID):
                return httpx.Response(200, json={"data": LEVY})
            return httpx.Response(404, json={"success": False, "error": {"code": "not_found", "message": "no type"}})
        if path == "/v1/documents/readings":
            body = json.loads(request.content)
            asked = (str(body["fileId"]), str(body["ocr"]))
            self.ocr.append(asked[1])
            if asked not in self.readings:
                self.reads += 1
                self.readings[asked] = self.polls
            return httpx.Response(
                202 if self.readings[asked] else 200,
                json={"data": self._reading(asked[0], "reading" if self.readings[asked] else "done")},
            )
        if path.startswith("/v1/documents/readings/"):
            asked = (path.rsplit("/", 1)[-1], request.url.params["ocr"])
            self.readings[asked] = max(0, self.readings[asked] - 1)
            return httpx.Response(
                200, json={"data": self._reading(asked[0], "reading" if self.readings[asked] else "done")}
            )
        if path == "/v1/documents/extractions":
            body = json.loads(request.content)
            key = request.headers["Idempotency-Key"]
            if key in self.keys and self.keys[key] != body:
                conflict = {"code": "idempotency_conflict", "message": "the key was used for another request"}
                return httpx.Response(409, json={"success": False, "error": conflict})
            if key in self.keys and not self.polls:
                return httpx.Response(200, json={"data": self._done(body)})
            self.keys[key] = body
            self.reads += 1
            self.asked.append(body)
            if self.polls:
                return httpx.Response(202, json={"data": {"id": "ext_1", "status": "running"}})
            return httpx.Response(200, json={"data": self._done(body)})
        if path == "/v1/documents/extractions/ext_1":
            self.polls -= 1
            status = "running" if self.polls > 0 else "done"
            answer = {"id": "ext_1", "status": status, **(self._done(self.asked[-1]) if status == "done" else {})}
            return httpx.Response(200, json={"data": answer})
        return httpx.Response(404, json={"success": False, "error": {"code": "no_route", "message": path}})

    def _done(self, body: dict[str, Any]) -> dict[str, Any]:
        fields = {"amount": {"value": 1500, "confidence": 0.96, "needsReview": False}}
        return {"id": "ext_1", "status": "done", "outcome": "ok", "fields": fields, "documentType": {"id": LEVY_ID}}

    def client(self) -> DocumentsClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.handle), base_url="http://documents")
        return DocumentsClient(
            ServiceClient(http, dev_service_signer(), "tools", "documents", ["documents:view", "documents:run"])
        )


async def _upload(files: FakeFilesService, team: str, name: str, text: str = "x", *, scan: str = "clean") -> str:
    client = files.client(service="kb", scopes=["files:view", "files:create", "files:edit"])
    stored = await client.write(
        TENANT, team, text.encode(), name=name, mime="text/plain", purpose="case_attachment", uploaded_by="maya"
    )
    files.files[stored.file.id]["scan"] = {"status": scan}
    return stored.file.id


async def _rig(texts: dict[str, str] | None = None, **docs: Any) -> tuple[FileTools, FakeFilesService, FakeDocuments]:
    files, documents = FakeFilesService(), FakeDocuments(texts=texts or {}, **docs)
    tools = FileTools(files.client(service="tools", scopes=["files:view"]), documents.client(), sleep=_no_wait)
    return tools, files, documents


async def _no_wait(_s: float) -> None:
    return None


async def _call(tools: FileTools, tool: str, team: str = OPS, **arguments: Any) -> Any:
    return await tools.run(tool, arguments, tenant=TENANT, team=team)


async def test_a_file_is_read_by_name_and_its_fields_by_type() -> None:
    tools, files, documents = await _rig()
    fid = await _upload(files, OPS, "levy-notice.txt")
    documents.texts[fid] = "Levy of 1,500.00 on account CHQ-2219"
    text = await _call(tools, "read_file", file="levy-notice.txt")
    assert text.ok and text.output["text"].startswith("Levy of 1,500.00"), text.output
    assert documents.ocr == ["auto"], "a scan is read only with OCR on"
    fields = await _call(tools, "read_document", file=fid, documentType="Levy notice")
    assert fields.ok and fields.output["fields"]["amount"]["value"] == 1500, fields.output
    assert documents.asked[-1]["documentTypeId"] == "dt_levy"
    # The same reads again, in a later turn, are the reads already made: nothing is read or paid for twice.
    reads = documents.reads
    assert (await _call(tools, "read_file", file=fid)).ok and (
        await _call(tools, "read_document", file=fid, documentType="dt_levy")
    ).ok
    assert documents.reads == reads


async def test_a_file_the_scan_has_not_cleared_is_not_read() -> None:
    tools, files, documents = await _rig()
    fid = await _upload(files, OPS, "new.txt", scan="pending")
    read = await _call(tools, "read_file", file=fid)
    assert not read.ok and "virus scan" in read.output["error"] and documents.reads == 0


async def test_another_teams_file_is_not_found() -> None:
    tools, files, _ = await _rig()
    fid = await _upload(files, RETAIL, "levy-notice.txt")
    by_name = await _call(tools, "read_file", file="levy-notice.txt")
    by_id = await _call(tools, "read_file", file=fid)
    type_elsewhere = await _call(tools, "read_document", team=RETAIL, file=fid, documentType="dt_levy")
    assert not by_name.ok and "no file named" in by_name.output["error"]
    assert not by_id.ok and not type_elsewhere.ok and "no document type" in type_elsewhere.output["error"]


async def test_an_ambiguous_name_lists_the_matches() -> None:
    tools, files, _ = await _rig()
    await _upload(files, OPS, "levy-notice-march.txt", "a")
    await _upload(files, OPS, "levy-notice-april.txt", "b")
    found = await _call(tools, "read_file", file="levy-notice")
    assert not found.ok and len(found.output["files"]) == 2, found.output


async def test_text_is_cut_with_a_note() -> None:
    tools, files, documents = await _rig()
    fid = await _upload(files, OPS, "contract.txt")
    documents.texts[fid] = "w" * (TEXT_LIMIT + 10)
    read = await _call(tools, "read_file", file=fid)
    assert read.ok and len(read.output["text"]) == TEXT_LIMIT and "Cut at" in read.output["note"]


async def test_a_large_files_read_is_waited_for() -> None:
    tools, files, documents = await _rig(polls=3)
    fid = await _upload(files, OPS, "big.txt")
    documents.texts[fid] = "the whole book"
    read = await _call(tools, "read_file", file=fid)
    assert read.ok and read.output["text"] == "the whole book", read.output


async def test_a_refusal_is_a_tool_error() -> None:
    tools, files, _ = await _rig(refuse=(422, "unreadable", "the file has no text layer"))
    fid = await _upload(files, OPS, "scan.txt")
    read = await _call(tools, "read_file", file=fid)
    assert not read.ok and "no text layer" in read.output["error"], read.output


async def test_every_install_serves_them_and_shows_their_cards(local_catalog: Any, store: Any, tenant: str) -> None:
    registry = ToolRegistry(local_catalog, store)
    resolved = [await registry.resolve(t, tenant_id=tenant) for t in ("read_file", "read_document")]
    assert all(r is not None and r.access == "read" for r in resolved), resolved
    assert {"read_file", "read_document"} <= {t["name"] for t in await registry.grantable(tenant)}
    assert {"files", "document-types"} <= {str(a["id"]) for a in BUILT_IN}


async def test_a_file_named_by_the_model_reaches_only_the_one_file_route(monkeypatch: Any) -> None:
    asked: list[bytes] = []
    real = FakeFilesService.handle

    def seen(self: FakeFilesService, request: httpx.Request) -> httpx.Response:
        asked.append(request.url.raw_path)
        return real(self, request)

    monkeypatch.setattr(FakeFilesService, "handle", seen)
    tools, _, documents = await _rig()
    # A file's text can steer the model's arguments: these would climb out of /v1/files/{id} to another route.
    for ref in ("../scan-results", "..", "x/content", "x?purpose=chat_attachment"):
        out = await _call(tools, "read_file", file=ref)
        assert not out.ok, out.output
    by_id = [p for p in asked if not p.startswith(b"/v1/files?")]
    assert by_id == [b"/v1/files/x%3Fpurpose%3Dchat_attachment"], by_id
    assert documents.reads == 0
