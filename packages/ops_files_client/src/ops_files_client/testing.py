"""files-service's public file routes as services call them through FilesClient (kb-service, documents-service),
faked with httpx MockTransport so a service's tests never boot another service's app. The fake keeps what the real
service promises: a file belongs to the team its token names, the same bytes in one team are stored once, bytes are
readable only once scanned clean (423 before), and only a token with `files:decide` records a verdict."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from ops_files_client import FilesClient
from ops_identity import ServiceClient, dev_service_signer


def _claims(request: httpx.Request) -> dict[str, Any]:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    body = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def _error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(
        status, json={"success": False, "error": {"code": code, "message": message, "status": status}}
    )


@dataclass
class FakeFilesService:
    files: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    blobs: dict[str, bytes] = field(default_factory=dict[str, bytes])
    # A file's references, (type, refId) pairs; attaching the same pair twice keeps one, as files-service does.
    references: dict[str, set[tuple[str, str]]] = field(default_factory=dict[str, set[tuple[str, str]]])
    # A status every call answers with, standing in for a files-service that refuses kb-service's token.
    refuse: int | None = None

    def _info(self, f: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in f.items() if k != "tenant"}

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.refuse is not None:
            return _error(self.refuse, "unauthorized", "Sign in, or send a valid API key.")
        claims = _claims(request)
        tenant, team = claims.get("tenant_id"), claims.get("team_id")
        scopes = cast(list[str], claims.get("scopes") or [])
        path = request.url.path
        if request.method == "POST" and path == "/v1/files":
            data = request.content
            digest = hashlib.sha256(data).hexdigest()
            same = next(
                (f for f in self.files.values() if (f["tenant"], f["team"], f["digest"]) == (tenant, team, digest)),
                None,
            )
            if same is not None:
                return httpx.Response(201, json={"data": {"file": self._info(same), "deduplicated": True}})
            fid = f"fil_{len(self.files) + 1:04d}"
            p = request.url.params
            self.files[fid] = {
                "id": fid, "tenant": tenant, "team": team, "name": p["name"], "mime": request.headers["Content-Type"],
                "size": len(data), "digest": digest, "purpose": p["purpose"], "uploadedBy": p["uploadedBy"],
                "scan": {"status": "pending"}, "referenceCount": 0,
            }  # fmt: skip
            self.blobs[fid] = data
            return httpx.Response(201, json={"data": {"file": self._info(self.files[fid]), "deduplicated": False}})
        if request.method == "POST" and path == "/v1/files/scan-results":
            if "files:decide" not in scopes:
                return _error(403, "scope_required", "files:decide is needed to record a scan verdict")
            body = json.loads(request.content)
            f = self.files.get(body["fileId"])
            if f is None or f["tenant"] != tenant:
                return _error(404, "not_found", "no such file")
            f["scan"] = {"status": body["status"], "engine": body.get("engine")}
            return httpx.Response(200, json={"data": self._info(f)})
        if request.method == "POST" and (m := re.fullmatch(r"/v1/files/([^/]+)/references", path)):
            f = self.files.get(m.group(1))
            if f is None or (f["tenant"], f["team"]) != (tenant, team):
                return _error(404, "not_found", "no such file in this team")
            if f["scan"]["status"] != "clean":
                return _error(409, "file_not_clean", f"the file is {f['scan']['status']}")
            body = json.loads(request.content)
            refs = self.references.setdefault(f["id"], set())
            refs.add((body["type"], body["refId"]))
            f["referenceCount"] = len(refs)
            return httpx.Response(200, json={"data": self._info(f)})
        if request.method == "DELETE" and (m := re.fullmatch(r"/v1/files/([^/]+)/references/([^/]+)/([^/]+)", path)):
            f = self.files.get(m.group(1))
            if f is None or (f["tenant"], f["team"]) != (tenant, team):
                return _error(404, "not_found", "no such file in this team")
            refs = self.references.setdefault(f["id"], set())
            refs.discard((m.group(2), m.group(3)))
            f["referenceCount"] = len(refs)
            return httpx.Response(200, json={"data": self._info(f)})
        if m := re.fullmatch(r"/v1/files/([^/]+)(/content)?", path):
            f = self.files.get(m.group(1))
            if f is None or (f["tenant"], f["team"]) != (tenant, team):
                return _error(404, "not_found", "no such file in this team")
            if not m.group(2):
                return httpx.Response(200, json={"data": self._info(f)})
            if f["scan"]["status"] != "clean":
                return _error(423, "not_scanned", f"the file is {f['scan']['status']}")
            return httpx.Response(200, content=self.blobs[f["id"]])
        return _error(404, "no_route", f"{request.method} {path} is not faked")

    def client(self, *, service: str = "kb", scopes: list[str] | None = None) -> FilesClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.handle), base_url="http://files")
        granted = scopes if scopes is not None else ["files:view", "files:create", "files:edit"]
        return FilesClient(ServiceClient(http, dev_service_signer(), service, "files", granted))
