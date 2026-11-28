"""A file's reading for knowledge, from documents-service: kb-service never parses a file it indexes, it asks for the
file's reading (made once per file content and OCR settings, whoever asks) and splits that. A reading that needs OCR is
made in the background; documents-service reports `reading.finished` to POST /v1/events, and the knowledge schedule
asks again for any item still reading, in case an event was missed."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from ops_documents_client import READING_PENDING, DocumentsClient
from ops_ingest import ParsedDocument
from ops_ingest.reading import FileFacts, Page, Reading, ReadingSettings, to_parsed_document
from ops_service_kit.http import JsonValue

__all__ = ["READING_PENDING", "DocumentsReadings", "ReadingAnswer", "Readings", "parsed_of", "read_with"]


class Readings(Protocol):
    async def reading(
        self, tenant: str, team: str, file_id: str, *, ocr: str, pictures: str | None = None
    ) -> dict[str, JsonValue]:
        """documents-service's answer for the file's reading: done with its pages, queued or reading, or failed."""
        ...


class DocumentsReadings:
    def __init__(self, documents: DocumentsClient) -> None:
        self.documents = documents

    async def reading(
        self, tenant: str, team: str, file_id: str, *, ocr: str, pictures: str | None = None
    ) -> dict[str, JsonValue]:
        return await self.documents.reading(tenant, team, file_id, ocr=ocr, pictures=pictures)


class ReadingFailure(BaseModel):
    message: str | None = None


class ReadingAnswer(BaseModel):
    """documents-service's answer about a file's reading, as the fields kb-service uses: its status, why it failed, and
    when it is done the reader version, settings, facts and pages."""

    status: str | None = None
    error: ReadingFailure | None = None
    readerVersion: str | None = None  # noqa: N815 - the wire name
    settings: ReadingSettings | None = None
    facts: FileFacts | None = None
    pages: list[Page] = []
    # The PDF a Word file or deck was drawn into, scanned clean; None when the file is not drawn.
    renditionId: str | None = None  # noqa: N815 - the wire name


def read_with(answer: ReadingAnswer) -> str:
    """How an item was read: the reader version and its settings, so a change to either reads it again."""
    settings = answer.settings
    return f"{answer.readerVersion}:{settings.ocr if settings else None}:{settings.language if settings else None}"


def parsed_of(
    answer: ReadingAnswer,
    *,
    fields: dict[str, str] | None = None,
    furniture: bool = False,
    main_content: bool = False,
) -> ParsedDocument:
    """A finished reading as the document `split` takes, with the blocks the source's cleaning drops left out."""
    if answer.facts is None:
        raise ValueError("a finished reading names the file's facts")
    reading = Reading(
        reader_version=str(answer.readerVersion),
        settings=answer.settings or ReadingSettings(),
        facts=answer.facts,
        pages=answer.pages,
    )
    return to_parsed_document(reading, fields=fields, furniture=furniture, main_content=main_content)
