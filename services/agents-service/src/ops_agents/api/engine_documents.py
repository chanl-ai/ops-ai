"""The workflow runner's DocumentsPort, DocumentTypesPort and FileDataPort in agents-service: an Extract from file step
asks documents-service's extraction API (its Full text the file's shared reading), Extract from text a document type's
fields, a Purge step its purge, and a Save data on file step files-service, each as the run's own team, through the
services' clients (never their code). Another team's or tenant's file is not found, as the service answers it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from ops_documents_client import DocumentsClient, DocumentsRefused
from ops_engine.ports import outside_call
from ops_engine.store import RunStore
from ops_files_client import FilesClient
from ops_service_kit.http import Json

from ..store.engine import EngineTransactions
from ..store.tenancy import current_tenant


@dataclass
class DocumentsExtractions:
    client: DocumentsClient
    tx: EngineTransactions

    async def extract(self, run_id: str, file_id: str, request: Json, *, key: str) -> Json:
        run = await RunStore(self.tx).row(run_id)
        if run is None:
            raise LookupError(f"run {run_id} is gone")
        with outside_call():
            return await self.client.extract(current_tenant(), run.team_id, file_id, request, idempotency_key=key)

    async def reading(self, run_id: str, file_id: str, *, ocr: str, ask: bool) -> Json:
        """The file's shared reading as it is now, asked for when `ask`; one still under way is never waited for here:
        the step parks on reading.finished instead."""
        team = await _team(self.tx, run_id)
        with outside_call():
            if ask:
                return await self.client.reading(current_tenant(), team, file_id, ocr=ocr)
            return await self.client.reading_now(current_tenant(), team, file_id, ocr=ocr)

    async def purge(self, run_id: str, file_id: str) -> Json:
        team = await _team(self.tx, run_id)
        with outside_call():
            return await self.client.purge(current_tenant(), team, file_id)

    async def correct(self, run_id: str, extraction_id: str, corrections: list[Json], *, entered_by: str) -> Json:
        team = await _team(self.tx, run_id)
        try:
            with outside_call():
                return await self.client.correct(
                    current_tenant(), team, extraction_id, corrections, entered_by=entered_by, checked=True
                )
        except DocumentsRefused as e:
            if e.status >= 500:
                raise
            # A refusal a retry cannot change (a value its type cannot hold, a read that is gone) takes the error port.
            return {"refused": {"code": e.code, "message": e.message}}

    async def fields(self, run_id: str, type_id: str, version: int | None) -> list[Json]:
        """The DocumentTypesPort: a document type's fields at `version`, the newest when None, read as the run's team
        (Extract from text). A version the type does not have is LookupError, so the step fails, not guesses."""
        return await type_fields(self.client, await _team(self.tx, run_id), type_id, version)


@dataclass
class RunFileData:
    client: FilesClient
    tx: EngineTransactions

    async def set_data(self, run_id: str, file_id: str, data: Json) -> Json:
        team = await _team(self.tx, run_id)
        with outside_call():
            return await self.client.set_data(current_tenant(), team, file_id, data)


async def type_fields(client: DocumentsClient, team: str, type_id: str, version: int | None) -> list[Json]:
    """A document type's fields at `version`, the newest when None, read as `team`: a workflow's Extract from text step
    and the AI step route read them here alike. A version the type does not have is LookupError."""
    with outside_call():
        found = await client.document_type(current_tenant(), team, type_id)
    versions = [cast(Json, v) for v in cast(list[Any], found.get("versions") or [])]
    chosen = (
        next((v for v in versions if v.get("version") == version), None)
        if version is not None
        else max(versions, key=lambda v: int(cast(int | str, v.get("version") or 0)), default=None)
    )
    if chosen is None:
        raise LookupError(f"document type {type_id} has no version {version}")
    return [cast(Json, f) for f in cast(list[Any], chosen.get("fields") or [])]


async def _team(tx: EngineTransactions, run_id: str) -> str:
    run = await RunStore(tx).row(run_id)
    if run is None:
        raise LookupError(f"run {run_id} is gone")
    return run.team_id
