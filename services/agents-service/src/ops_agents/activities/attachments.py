"""Files a banker attaches to one chat message (c-071): the bytes in an ops_storage object store under a retention
date, the text parsed once at upload by ops_ingest and kept, capped, as chat_attachments metadata. A turn cites an
attachment like a knowledge passage, page by page.

`ChatFileStore` is the one place bytes are written: agents-service may not use another service's internals (the
service boundary test), so it holds only ops_storage's public protocol, and it is what switches to the files-service
client once that service runs (c-087; wiki concepts/chat.md).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from ops_agent_kernel.ports import KnowledgePort
from ops_agent_kernel.types import Passage
from ops_ingest import parse
from ops_ingest.models import ParsedDocument, Table
from ops_ingest.parsers import TooLargeError, UnsupportedFormatError
from ops_service_kit.errors import Unprocessable
from ops_storage.base import ObjectStore
from ops_storage.local import LocalObjectStore

MAX_BYTES = 10 * 1024 * 1024
ALLOWED = {
    "application/pdf": "PDF",
    "text/plain": "text",
    "text/markdown": "Markdown",
    "text/csv": "CSV",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word (.docx)",
}
_BY_EXTENSION = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv"}
_BY_EXTENSION[".docx"] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Parsed text kept per file, and the share of it one turn may read; a file past either says so in the reply.
MAX_TEXT_CHARS = 200_000
TURN_TEXT_CHARS = 24_000
CHUNK_CHARS = 2_000
# Chat files are kept 90 days; the store refuses to delete one before then.
RETENTION_DAYS = 90


def refuse(message: str) -> Unprocessable:
    return Unprocessable(message, code="attachment_refused", details={"field": "file"})


def mime_of(name: str, given: str | None) -> str:
    """The file's type from its declared Content-Type, or its extension when none is declared; 422 for any other."""
    mime = (given or "").split(";")[0].strip().lower()
    if not mime or mime == "application/octet-stream":
        mime = _BY_EXTENSION.get(Path(name).suffix.lower(), "")
    if mime not in ALLOWED:
        kinds = ", ".join(ALLOWED.values())
        raise refuse(f"{name} is not a type chat can read. Attach {kinds}, up to {MAX_BYTES // (1024 * 1024)} MB.")
    return mime


@dataclass(frozen=True)
class Page:
    page: int | None
    section: str
    text: str


def pages_of(doc: ParsedDocument) -> list[Page]:
    """The document as page-sized runs of text, each with its page and heading, for citing."""
    out: list[Page] = []
    for s in doc.sections:
        for b in s.blocks:
            text = (
                "\n".join([" | ".join(b.headers), *(" | ".join(r) for r in b.rows)]) if isinstance(b, Table) else b.text
            )
            if not text.strip():
                continue
            page, heading = b.page or s.page, " > ".join(s.heading_path)
            if out and out[-1].page == page and out[-1].section == heading and len(out[-1].text) < CHUNK_CHARS:
                out[-1] = Page(page, heading, f"{out[-1].text}\n{text}")
            else:
                out.append(Page(page, heading, text))
    return out


@dataclass(frozen=True)
class Parsed:
    pages: list[Page]
    truncated: bool


def read(data: bytes, *, name: str, mime: str) -> Parsed:
    """Parsed once at upload. A file with no text layer, or one the parser refuses, is a 422 at upload, not a turn
    that quietly answers without it."""
    try:
        doc = parse(data, filename=name, mime_type=mime)
    except (UnsupportedFormatError, TooLargeError, ValueError) as e:
        raise refuse(f"{name} could not be read: {e}") from e
    pages, used = pages_of(doc), 0
    kept: list[Page] = []
    for p in pages:
        if used + len(p.text) > MAX_TEXT_CHARS:
            return Parsed(kept, truncated=True)
        kept.append(p)
        used += len(p.text)
    if not kept:
        raise refuse(f"{name} has no text chat can read (a scan without a text layer is not read).")
    return Parsed(kept, truncated=False)


class ChatFileStore:
    """Writes an attachment's bytes through an ops_storage object store: a presigned PUT, then a retention date.

    Interim (orch ruling, 2026-10-17): ops_storage is a shared library agents-service may use; ops_files is the files
    service's domain and no service imports it. c-087 replaces this adapter with the files-service client and migrates
    the `fl_` ids it issued."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    @classmethod
    def local(cls, root: Path) -> ChatFileStore:
        # Upload URLs are redeemed in this process the moment they are signed, so a per-process key is enough.
        return cls(LocalObjectStore(root, signing_key=os.urandom(32)))

    def put(self, data: bytes, *, mime: str, team: str) -> str:
        """Stores the bytes under a new file id and returns it; the caller checked size and type."""
        file_id = f"fl_{uuid.uuid4().hex[:16]}"
        key = f"chat/{team}/{file_id}"
        put = self._store.presign_put(key, content_type=mime, max_bytes=len(data), expires_in=60)
        if isinstance(self._store, LocalObjectStore):
            self._store.receive_put(put.url, put.headers, data)
        else:
            httpx.put(put.url, headers=dict(put.headers), content=data, timeout=60).raise_for_status()
        self._store.set_retention(key, datetime.now(UTC) + timedelta(days=RETENTION_DAYS), "governance")
        return file_id


def passages(name: str, file_id: str, pages: list[Page], budget: int = TURN_TEXT_CHARS) -> tuple[list[Passage], bool]:
    """An attachment's pages as passages a turn can cite, within this turn's share of text; True when some were cut."""
    out: list[Passage] = []
    for p in pages:
        if budget - len(p.text) < 0:
            return out, True
        budget -= len(p.text)
        out.append(Passage(file_id, name, p.section or name, "attached", p.text, "attachment", p.page))
    return out, False


@dataclass
class WithAttachments:
    """The turn's knowledge: the attached files' passages first, then whatever the knowledge bases find. Attached
    files are what the person asked about, so they are never crowded out by the bases."""

    inner: KnowledgePort
    attached: list[Passage]

    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Passage]:
        words = {w for w in query.lower().split() if len(w) > 3}
        ranked = sorted(self.attached, key=lambda p: -sum(w in p.text.lower() for w in words))
        bases = [i for i in kb_ids if i != "attachment"]
        found = await self.inner.search(query, bases, k=k) if bases else []
        return [*ranked[:k], *found]
