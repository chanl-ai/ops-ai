# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""`uv run python -m ops_documents`: documents-service on settings.documents_port (8760). It reads file bytes from
files-service at settings.files_url as the caller's team, and calls models-service with its own key."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI

from ops_documents.app import create_documents_app
from ops_documents.document_types import default_document_types
from ops_documents.extraction import default_extractor
from ops_documents.files import Files
from ops_documents.layouts import Layouts
from ops_documents.store import LayoutsStore, engine_for
from ops_documents.store.event_relay import keep_relaying
from ops_files_client import FilesClient
from ops_identity import Auth, ServiceClient
from ops_service_kit.logging import configure_logging
from ops_service_kit.settings import Settings
from ops_store.schema_version import require_current_schema

# This service's own migration chain: it starts only on a database that records the chain's head.
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def build(settings: Settings) -> FastAPI:
    """The app on its database, files-service and models-service; building it opens no connection."""
    engine = engine_for(settings.database_url)
    files = Files(FilesClient.from_settings(settings, service="documents", scopes=["files:view", "files:edit"]))
    extractor = default_extractor(files, engine, settings, layouts=Layouts(files, LayoutsStore(engine)))
    types = default_document_types(files, engine, settings, extractor)
    background: list[Callable[[], Coroutine[Any, Any, None]]] = []
    if settings.agents_url:
        # A correction's extraction.corrected reaches agents-service, which saves the corrected read on the file.
        http = httpx.AsyncClient(base_url=settings.agents_url, timeout=5)
        agents = ServiceClient.for_settings(
            settings, http, service="documents", audience="agents", scopes=["events:emit"]
        )
        background.append(lambda: keep_relaying(engine, agents))
    return create_documents_app(
        engine=engine,
        extractor=extractor,
        document_types=types,
        auth=Auth.from_settings(settings, audience="documents"),
        background=background,
    )


def main() -> None:
    settings = Settings()
    require_current_schema(settings.database_url, MIGRATIONS)
    configure_logging()
    uvicorn.run(build(settings), host=settings.bind_host, port=settings.documents_port, log_level="info")


if __name__ == "__main__":
    main()
