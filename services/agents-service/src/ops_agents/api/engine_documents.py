"""The workflow runner's DocumentsPort, DocumentTypesPort and FileDataPort in agents-service (c-157, c-235, c-256,
c-250, c-298): an Extract from file step asks documents-service's extraction API, Extract from text a document type's
fields, a Purge step its purge, and a Save data on file step files-service, each as the run's own team, through the
services' clients (never their code). Another team's or tenant's file is not found, as the service answers it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from ops_documents_client import DocumentsClient
from ops_engine.store import RunStore
from ops_files_client import FilesClient

from ..store.engine import EngineTransactions
from ..store.tenancy import current_tenant


@dataclass
class DocumentsExtractions:
    client: DocumentsClient
    tx: EngineTransactions

    async def extract(self, run_id: str, file_id: str, request: dict[str, Any], *, key: str) -> dict[str, Any]:
        run = await RunStore(self.tx).get(run_id)
        if run is None:
            raise LookupError(f"run {run_id} is gone")
        return await self.client.extract(current_tenant(), str(run["team_id"]), file_id, request, idempotency_key=key)

    async def purge(self, run_id: str, file_id: str) -> dict[str, Any]:
        return await self.client.purge(current_tenant(), await _team(self.tx, run_id), file_id)

    async def fields(self, run_id: str, type_id: str, version: int | None) -> list[dict[str, Any]]:
        """The DocumentTypesPort: a document type's fields at `version`, the newest when None, read as the run's team
        (Extract from text, c-298). A version the type does not have is LookupError, so the step fails, not guesses."""
        return await type_fields(self.client, await _team(self.tx, run_id), type_id, version)


@dataclass
class RunFileData:
    client: FilesClient
    tx: EngineTransactions

    async def set_data(self, run_id: str, file_id: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self.client.set_data(current_tenant(), await _team(self.tx, run_id), file_id, data)


async def type_fields(client: DocumentsClient, team: str, type_id: str, version: int | None) -> list[dict[str, Any]]:
    """A document type's fields at `version`, the newest when None, read as `team`: a workflow's Extract from text step
    and the AI step route read them here alike. A version the type does not have is LookupError."""
    found = await client.document_type(current_tenant(), team, type_id)
    versions = [cast(dict[str, Any], v) for v in cast(list[Any], found.get("versions") or [])]
    chosen = (
        next((v for v in versions if v.get("version") == version), None)
        if version is not None
        else max(versions, key=lambda v: int(v.get("version") or 0), default=None)
    )
    if chosen is None:
        raise LookupError(f"document type {type_id} has no version {version}")
    return [cast(dict[str, Any], f) for f in cast(list[Any], chosen.get("fields") or [])]


async def _team(tx: EngineTransactions, run_id: str) -> str:
    run = await RunStore(tx).get(run_id)
    if run is None:
        raise LookupError(f"run {run_id} is gone")
    return str(run["team_id"])
