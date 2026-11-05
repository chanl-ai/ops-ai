"""What a chat turn gives the agent about the files attached to its thread. A file is files-service's (uploaded by
the console as `chat_attachment`, or any file of the team named by its id), read as the person's team; its text is
documents-service's full-text read, the same read an agent's read_file tool makes, so a file is read once whoever
asks. A file named on the message being sent that the team does not hold is a 404. Every other problem (a file no
longer in Files, one the scan has not cleared, one with no text) is told to the agent beside the file's name and id,
and, for a file on this message, to the person in the reply. The conversation records no reference on the file, so a
person can delete a file they attached; the message keeps its name and a later turn says it is no longer in Files."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ops_agent_kernel.types import AttachedFile
from ops_agents.activities import attachments
from ops_contracts.chat import ChatAttachment
from ops_documents_client import READING, DocumentsClient, DocumentsRefused
from ops_files_client import FileInfo, FileNotFound, FilesClient, FilesRefused
from ops_identity import ServiceUnreachable
from ops_service_kit.errors import NotFound, ServiceUnavailable

# How long a turn waits for documents-service to read a large file in the background before answering without it.
READ_WAIT_S = 20.0
GONE = "it is no longer in Files"
SCAN = {
    "pending": "the virus scan has not cleared it yet",
    "infected": "the virus scan quarantined it",
    "failed": "the virus scan could not check it",
}
NO_TEXT = "it has no text to read (a scan or photo without a text layer)"
STILL_READING = "it is still being read; ask again in a moment"


@dataclass
class TurnFiles:
    """The thread's attachments as one turn reads them: what the agent is told about each file, the passages it may
    cite, and the sentences the reply ends with for the person."""

    files: list[AttachedFile] = field(default_factory=list[AttachedFile])
    passages: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    notes: list[str] = field(default_factory=list[str])


class ChatAttachmentReader:
    def __init__(self, files: FilesClient, documents: DocumentsClient, *, wait_s: float = READ_WAIT_S) -> None:
        self.files, self.documents, self.wait_s = files, documents, wait_s

    async def read(
        self,
        tenant: str,
        team: str,
        *,
        asked: list[ChatAttachment],
        earlier: list[ChatAttachment],
    ) -> TurnFiles:
        out, budget, cut = TurnFiles(), attachments.TURN_TEXT_CHARS, list[str]()
        new = {a.file_id for a in asked}
        # This message's files first: they are what the person is asking about, so they get the turn's text first.
        named = {a.file_id: a for a in [*asked, *earlier] if a.file_id}
        for file_id, given in named.items():
            found = await self._file(tenant, team, file_id, required=file_id in new)
            if isinstance(found, str):
                out.files.append(AttachedFile(file_id, given.name, unread=found))
                continue
            unread, pages = await self._text(tenant, team, found)
            out.files.append(AttachedFile(file_id, found.name, unread=unread))
            if unread:
                if file_id in new:
                    out.notes.append(f"{found.name} could not be read: {unread}.")
                continue
            found_passages, was_cut = attachments.passages(found.name, file_id, pages, budget)
            budget -= sum(len(p.text) for p in found_passages)
            out.passages += [
                {"documentId": p.document_id, "title": p.title, "section": p.section, "page": p.page, "text": p.text}
                for p in found_passages
            ]
            if was_cut:
                cut.append(found.name)
        if cut:
            out.notes.append(
                f"Only part of {', '.join(cut)} was read; ask about a specific page or section for the rest."
            )
        return out

    async def _file(self, tenant: str, team: str, file_id: str, *, required: bool) -> FileInfo | str:
        """The team's file, or why it cannot be read; a file named on this message that the team lacks is a 404."""
        try:
            found = await self.files.get(tenant, team, file_id)
        except FileNotFound as e:
            if required:
                raise NotFound(f"Attachment {file_id}") from e
            return GONE
        except (FilesRefused, ServiceUnreachable) as e:
            raise ServiceUnavailable("Files cannot be reached, so the attached files cannot be read.") from e
        return found if found.scan.status == "clean" else SCAN[found.scan.status]

    async def _text(self, tenant: str, team: str, file: FileInfo) -> tuple[str | None, list[attachments.Page]]:
        try:
            read = await self.documents.read_text(tenant, team, file.id, digest=file.digest, wait_s=self.wait_s)
        except DocumentsRefused as e:
            return e.message.rstrip("."), []
        except ServiceUnreachable:
            return "the document reader cannot be reached", []
        status = read.get("status")
        if status in READING:
            return STILL_READING, []
        if status == "unreadable":
            return NO_TEXT, []
        if status != "done":
            error: dict[str, Any] = read.get("error") or {}
            return str(error.get("message") or "the document reader could not read it").rstrip("."), []
        pages = attachments.pages_of(read)
        return (None, pages) if pages else (NO_TEXT, [])
