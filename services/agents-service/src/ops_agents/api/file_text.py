"""An email attachment's text for a workflow graph, from the file's reading in documents-service (OCR as configured,
auto by default), as the run's tenant and team: the graph never parses a file itself."""

from __future__ import annotations

from ops_documents_client import READING_PENDING, DocumentsClient, DocumentsRefused, reading_text
from ops_identity import ServiceUnreachable
from ops_store import isolation

# How long a graph step waits for a scanned attachment's background reading before going on without its text.
READ_WAIT_S = 60.0


class ReadingText:
    def __init__(self, documents: DocumentsClient, *, ocr: str = "auto", wait_s: float = READ_WAIT_S) -> None:
        self.documents, self.ocr, self.wait_s = documents, ocr, wait_s

    async def read_file(self, file_id: str) -> str:
        """The file's text, page after page; empty when it has none, is still being read, or cannot be read."""
        team = isolation.team()
        if not team:
            return ""
        try:
            answer = await self.documents.reading(isolation.tenant(), team, file_id, ocr=self.ocr, wait_s=self.wait_s)
        except (DocumentsRefused, ServiceUnreachable):
            return ""
        if answer.get("status") in READING_PENDING:
            return ""
        return reading_text(answer)
