"""documents-service's readings as kb-service asks for them, made in this process by the one reader
(ops_ingest.reading) from the bytes the source's file store holds, so a sync test splits the reading a real
documents-service would give. Each file and OCR mode is read once and kept, as documents-service keeps it; `pending`
answers a file's next asks as still reading, and `down` as documents-service out of reach."""

from __future__ import annotations

from typing import Any

from ops_identity import ServiceUnreachable
from ops_ingest.parsers.ocr import WordOcr
from ops_ingest.reading import ReadingError, ReadingSettings, read
from ops_kb.files import FileIntake


class LocalReadings:
    def __init__(self, intake: FileIntake, *, engine: WordOcr | None = None) -> None:
        self.intake, self.engine = intake, engine
        self.pending: dict[str, int] = {}
        self.down = False
        # Each time a file's bytes were read, by file id: a second ask for a kept reading reads nothing.
        self.reads: list[str] = []
        self.kept: dict[tuple[str, str], dict[str, Any]] = {}

    async def reading(self, tenant: str, team: str, file_id: str, *, ocr: str) -> dict[str, Any]:
        if self.down:
            raise ServiceUnreachable("documents-service did not answer")
        head = {"fileId": file_id, "readerVersion": "reading-1", "settings": {"ocr": ocr, "language": "eng"}}
        if self.pending.get(file_id):
            self.pending[file_id] -= 1
            return {**head, "status": "reading"}
        if (file_id, ocr) in self.kept:
            return self.kept[(file_id, ocr)]
        name, mime, data = await self.intake.read(tenant, team, file_id)
        self.reads.append(file_id)
        try:
            made = read(data, filename=name, mime_type=mime, settings=ReadingSettings(ocr=ocr), ocr_engine=self.engine)  # pyright: ignore[reportArgumentType]
        except ReadingError as e:
            return {**head, "status": "failed", "error": {"code": e.code, "message": str(e)}}
        answer = {
            **head,
            "status": "done",
            "readerVersion": made.reader_version,
            "facts": made.facts.model_dump(mode="json", by_alias=True),
            "pages": [p.model_dump(mode="json", by_alias=True) for p in made.pages],
        }
        self.kept[(file_id, ocr)] = answer
        return answer
