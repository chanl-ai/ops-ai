"""Each step's output shape for one saved workflow version (c-353): `ops_engine.shapes` resolved against this
service's clients, so a document type's fields and an operation's response come from documents-service and
tools-service as the caller's team reads them."""

from __future__ import annotations

from typing import Any, cast

import httpx

from ops_documents_client import DocumentsClient, DocumentsRefused
from ops_engine import default_registry
from ops_engine.definition import WorkflowDefinition
from ops_engine.shapes import Ports, Shape, shapes, unknown_fields
from ops_identity import ServiceCallError, ServiceUnreachable

from .deps import Runtime
from .engine_documents import type_fields


class ServiceLookups:
    """`ops_engine.shapes.Lookups` on this service's clients. A service that refuses, cannot be reached, or does not
    find the record leaves that shape open: a shape is advice, so it never fails a save or a read."""

    def __init__(self, rt: Runtime, team: str, documents: DocumentsClient | None) -> None:
        self.rt, self.team, self.documents = rt, team, documents

    async def document_fields(self, type_id: str, version: int | None) -> list[dict[str, Any]]:
        # documents-service reads a document type as a team; with none named there is nothing it may answer.
        if self.documents is None or not self.team:
            return []
        try:
            return await type_fields(self.documents, self.team, type_id, version)
        except (DocumentsRefused, LookupError, httpx.HTTPError):
            return []

    async def operation_output(self, operation: str) -> Shape | None:
        if self.rt.tools is None or not operation:
            return None
        try:
            found = await self.rt.tools.tool_policy(operation)
        except (ServiceCallError, ServiceUnreachable, httpx.HTTPError):
            return None
        output = found.get("outputSchema")
        return cast(Shape, output) if isinstance(output, dict) else None


def _documents(rt: Runtime) -> DocumentsClient | None:
    if not rt.settings.documents_url:
        return None
    return DocumentsClient.from_settings(rt.settings, service="agents", scopes=["documents:view"])


async def version_shapes(rt: Runtime, team: str, definition: dict[str, Any]) -> dict[str, Ports]:
    documents = _documents(rt)
    try:
        d = WorkflowDefinition.model_validate(definition)
        return await shapes(d, default_registry(), ServiceLookups(rt, team, documents))
    finally:
        if documents is not None:
            await documents.aclose()


async def field_warnings(rt: Runtime, team: str, d: WorkflowDefinition) -> list[dict[str, Any]]:
    """`unknown_output_field` warnings for a definition being validated or saved."""
    documents = _documents(rt)
    try:
        return await unknown_fields(d, default_registry(), ServiceLookups(rt, team, documents))
    finally:
        if documents is not None:
            await documents.aclose()
