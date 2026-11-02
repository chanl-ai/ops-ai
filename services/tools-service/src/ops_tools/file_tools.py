"""The built-in Files and Document types tools (c-613, install flag `file_tools`): `read_file` gives an agent the full
text of a file its team uploaded, and `read_document` reads one of the team's document types' fields from a file. Both
are documents-service's own reads (the full-text read asks no model; a type's read is an extraction like any other),
called as the calling run's tenant and team, so another team's file or type is never found. They run behind the tool
gateway as the platform's local tools, so grants, the call log and the team's write rules apply as to any tool.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from ops_agent_kernel.ports import ToolOutcome
from ops_documents_client import DocumentNotFound, DocumentsClient, DocumentsRefused
from ops_files_client import FileInfo, FileNotFound, FilesClient, FilesRefused

from .modules.seed import FILE_TOOL_NAMES, FILE_TOOL_TIMEOUT_MS

READ_FILE, READ_DOCUMENT = FILE_TOOL_NAMES
# A file's text past this is cut, with a note: one long contract would otherwise fill the model's context.
TEXT_LIMIT = 20_000
# A large file's read is waited for within the operation's timeout, then the agent is told to ask again; the next ask
# finds the same read by its key.
WAIT_S = FILE_TOOL_TIMEOUT_MS / 1000 - 5
POLL_S = 1.0
# Files a name search offers when it matches several.
MATCHES = 10


def _reason(answer: dict[str, Any], otherwise: str) -> str:
    """Why documents-service could not read the file, as it said it."""
    error: dict[str, Any] = answer.get("error") or {}
    return str(error.get("message") or otherwise)


class FileTools:
    def __init__(
        self,
        files: FilesClient,
        documents: DocumentsClient,
        *,
        wait_s: float = WAIT_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.files, self.documents = files, documents
        self.wait_s, self.sleep = wait_s, sleep

    async def run(self, tool: str, arguments: dict[str, Any], *, tenant: str, team: str | None) -> ToolOutcome:
        if not team:
            return ToolOutcome(False, {"error": "A file belongs to a team; this call acts in none."})
        found = await self._file(tenant, team, str(arguments.get("file") or "").strip())
        if isinstance(found, ToolOutcome):
            return found
        if found.scan.status != "clean":
            # files-service serves no bytes until a scan clears the file; documents-service would refuse it too.
            return ToolOutcome(
                False, {"error": f"{found.name} is not cleared by the virus scan yet ({found.scan.status})."}
            )
        try:
            if tool == READ_FILE:
                return await self._text(tenant, team, found)
            return await self._fields(tenant, team, found, str(arguments.get("documentType") or "").strip())
        except DocumentNotFound:
            return ToolOutcome(False, {"error": f"{found.name} cannot be read: the team holds no such file."})
        except DocumentsRefused as e:
            # The reason documents-service gave (an unreadable file, a type with no fields), never a stack.
            return ToolOutcome(False, {"error": f"{found.name} could not be read: {e.message}", "code": e.code})

    async def _file(self, tenant: str, team: str, ref: str) -> FileInfo | ToolOutcome:
        """The team's file with this id, or the one file named so; a name matching several lists them."""
        if not ref:
            return ToolOutcome(False, {"error": "Name the file: its id, or its name."})
        try:
            return await self.files.get(tenant, team, ref)
        except FileNotFound:
            pass
        except FilesRefused as e:
            if e.status not in (400, 404, 422):
                return ToolOutcome(False, {"error": f"Files cannot be reached: {e.message}"})
        try:
            matches = await self.files.find(tenant, team, ref, limit=MATCHES)
        except FilesRefused as e:
            return ToolOutcome(False, {"error": f"Files cannot be searched: {e.message}"})
        exact = [f for f in matches if f.name.lower() == ref.lower()]
        picks = exact or matches
        if len(picks) == 1:
            return picks[0]
        if not picks:
            return ToolOutcome(False, {"error": f"The team has no file named {ref}."})
        listed = [{"fileId": f.id, "name": f.name, "type": f.mime} for f in picks]
        return ToolOutcome(
            False, {"error": f"Several of the team's files match {ref}; name one by its id.", "files": listed}
        )

    async def _finished(self, tenant: str, team: str, answer: dict[str, Any]) -> dict[str, Any]:
        """The extraction once it has finished, waiting for a large file's background read within the deadline."""
        ends = time.monotonic() + self.wait_s
        while answer.get("status") in ("queued", "running") and time.monotonic() < ends:
            await self.sleep(POLL_S)
            answer = await self.documents.extraction(tenant, team, str(answer["id"]))
        return answer

    async def _text(self, tenant: str, team: str, file: FileInfo) -> ToolOutcome:
        # Keyed by the file's bytes: a second read of the same file, in any turn, answers the read already made (or
        # still running), and costs nothing more.
        started = await self.documents.extract(
            tenant, team, file.id, {"read": "text"}, idempotency_key=f"file-tools:{file.digest}:text"
        )
        answer = await self._finished(tenant, team, started)
        head = {"fileId": file.id, "name": file.name, "type": file.mime, "sensitivity": file.sensitivity}
        if answer.get("status") in ("queued", "running"):
            return ToolOutcome(False, {**head, "error": "The file is still being read; ask again shortly."})
        if answer.get("status") != "done":
            reason = _reason(answer, "it has no text to read")
            return ToolOutcome(False, {**head, "error": f"{file.name} could not be read: {reason}"})
        text = str(answer.get("text") or "")
        out: dict[str, Any] = {**head, "text": text[:TEXT_LIMIT]}
        if len(text) > TEXT_LIMIT:
            out["note"] = f"Cut at {TEXT_LIMIT} of {len(text)} characters."
        return ToolOutcome(True, out)

    async def _type(self, tenant: str, team: str, ref: str) -> dict[str, Any] | None:
        """The team's document type with this id, or the one named so."""
        try:
            return await self.documents.document_type(tenant, team, ref)
        except DocumentNotFound:
            pass
        named = [
            t
            for t in await self.documents.document_types(tenant, team)
            if str(t.get("name", "")).lower() == ref.lower()
        ]
        return named[0] if len(named) == 1 else None

    async def _fields(self, tenant: str, team: str, file: FileInfo, ref: str) -> ToolOutcome:
        if not ref:
            return ToolOutcome(False, {"error": "Name the document type to read the file as."})
        kind = await self._type(tenant, team, ref)
        if kind is None:
            return ToolOutcome(False, {"error": f"The team has no document type {ref}."})
        version = kind.get("latestVersion") or kind.get("version")
        # Keyed by the bytes and the type version: the same document read with the same type is one model call.
        started = await self.documents.extract(
            tenant,
            team,
            file.id,
            {"documentTypeId": kind["id"], **({"version": version} if version else {})},
            idempotency_key=f"file-tools:{file.digest}:{kind['id']}@{version}",
        )
        answer = await self._finished(tenant, team, started)
        head = {
            "fileId": file.id,
            "name": file.name,
            "sensitivity": file.sensitivity,
            "documentType": answer.get("documentType") or {"id": kind["id"]},
        }
        if answer.get("status") in ("queued", "running"):
            return ToolOutcome(False, {**head, "error": "The document is still being read; ask again shortly."})
        if answer.get("status") != "done":
            reason = _reason(answer, "it could not be read")
            return ToolOutcome(False, {**head, "error": f"{file.name} could not be read: {reason}"})
        return ToolOutcome(True, {**head, "outcome": answer.get("outcome"), "fields": answer.get("fields") or {}})
