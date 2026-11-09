"""A file's reading for knowledge, from documents-service: kb-service never parses a file it indexes, it asks for the
file's reading (made once per file content and OCR settings, whoever asks) and splits that. A reading that needs OCR is
made in the background; documents-service reports `reading.finished` to POST /v1/events, and the knowledge schedule
asks again for any item still reading, in case an event was missed."""

from __future__ import annotations

from typing import Any, Protocol, cast

from ops_documents_client import READING_PENDING, DocumentsClient
from ops_ingest import ParsedDocument
from ops_ingest.reading import FileFacts, Page, Reading, ReadingSettings, to_parsed_document

__all__ = ["READING_PENDING", "DocumentsReadings", "Readings", "parsed_of", "read_with"]


class Readings(Protocol):
    async def reading(self, tenant: str, team: str, file_id: str, *, ocr: str) -> dict[str, Any]:
        """documents-service's answer for the file's reading: done with its pages, queued or reading, or failed."""
        ...


class DocumentsReadings:
    def __init__(self, documents: DocumentsClient) -> None:
        self.documents = documents

    async def reading(self, tenant: str, team: str, file_id: str, *, ocr: str) -> dict[str, Any]:
        return await self.documents.reading(tenant, team, file_id, ocr=ocr)


def read_with(answer: dict[str, Any]) -> str:
    """How an item was read: the reader version and its settings, so a change to either reads it again."""
    settings: dict[str, Any] = answer.get("settings") or {}
    return f"{answer.get('readerVersion')}:{settings.get('ocr')}:{settings.get('language')}"


def parsed_of(answer: dict[str, Any], *, fields: dict[str, str] | None = None) -> ParsedDocument:
    """A finished reading as the document `split` takes."""
    reading = Reading(
        reader_version=str(answer["readerVersion"]),
        settings=ReadingSettings.model_validate(answer.get("settings") or {}),
        facts=FileFacts.model_validate(answer["facts"]),
        pages=[Page.model_validate(p) for p in cast(list[dict[str, Any]], answer.get("pages") or [])],
    )
    return to_parsed_document(reading, fields=fields)
