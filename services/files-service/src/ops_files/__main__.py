# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""`uv run python -m ops_files`: files-service on settings.files_port (8750). Files go to the local backend under
settings.files_dir until a tenant's storage settings name another target (ops_files.settings)."""

from __future__ import annotations

import os
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import httpx
import uvicorn

from ops_files.app import create_files_app
from ops_files.models import PurposeLimit, RetentionClass
from ops_files.retention import keep_purging
from ops_files.scanning import EicarScanner
from ops_files.secrets import CredentialCipher
from ops_files.service import FilesConfig
from ops_files.settings import StorageSettings, build_store
from ops_files.store import FilesStore, SettingsStore, engine_for
from ops_files.store.event_relay import keep_relaying
from ops_files.tenant_files import TenantFiles
from ops_identity import Auth, ServiceClient
from ops_service_kit.logging import configure_logging
from ops_service_kit.settings import Settings, require_keys
from ops_storage.local import LocalObjectStore
from ops_store.schema_version import require_current_schema

# The classes files.md 4.4 names for the purposes this slice serves; a retention settings page replaces this list.
RETENTION_CLASSES = (
    RetentionClass(id="standard", name="Standard", days=None),
    RetentionClass(id="chat-90d", name="Chat attachment, 90 days", days=90, purposes=["chat_attachment"]),
    RetentionClass(id="knowledge", name="Knowledge source", days=None, purposes=["knowledge_source"]),
    RetentionClass(
        id="knowledge-snapshot",
        name="Knowledge snapshot, 30 days after its source lets it go",
        days=30,
        purposes=["knowledge_snapshot"],
        after_release=True,
    ),
)

# What each purpose accepts until a tenant saves its own limits in Storage settings. A chat attachment is read for the
# agent through documents-service, so it takes only the formats documents-service parses (ops_ingest.parsers.parse).
PURPOSE_LIMITS = (
    PurposeLimit(
        purpose="chat_attachment", allowed_types=["pdf", "docx", "xlsx", "csv", "html", "txt", "md"], max_size_mb=10
    ),
)

# This service's own migration chain: it starts only on a database that records the chain's head.
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


def files_config(settings: Settings) -> FilesConfig:
    environment = "dev" if settings.environment == "dev" else "test" if settings.environment == "test" else "prod"
    return FilesConfig(
        retention_classes=RETENTION_CLASSES,
        default_retention_class="standard",
        limits=PURPOSE_LIMITS,
        environment=environment,
    )


def build(settings: Settings) -> TenantFiles:
    # Signed local:// URLs never leave this process (browsers use the proxy routes), so a per-process key is enough.
    signing_key = os.urandom(32)
    store = LocalObjectStore(settings.files_dir / "objects", signing_key=signing_key)
    config = files_config(settings)
    # Refused here, not in Settings: every service builds Settings, and only files-service scans.
    if settings.files_scanning == "off" and settings.environment != "dev":
        raise ValueError("OPS_FILES_SCANNING=off is for dev only; outside dev name a scanner or the scan hook")
    scanning = {"off": "off", "eicar": "inline", "hook": "hook"}[settings.files_scanning]
    scanner = EicarScanner() if settings.files_scanning == "eicar" else None
    engine = engine_for(settings.database_url)
    storage = StorageSettings(
        SettingsStore(engine),
        CredentialCipher(settings.secrets_key.get_secret_value()),
        build_store(settings.files_dir, signing_key),
        config,
        default_store=store,  # pyright: ignore[reportArgumentType]
        default_proxy=True,
        scanning=settings.files_scanning,
    )
    return TenantFiles(store, FilesStore(engine), config, scanning=scanning, scanner=scanner, settings=storage)  # pyright: ignore[reportArgumentType]


def main() -> None:
    settings = Settings()
    require_keys(settings, "secrets_key")
    require_current_schema(settings.database_url, MIGRATIONS)
    configure_logging(service="files-service")
    files = build(settings)
    # Released knowledge snapshots are deleted once their days pass.
    background: list[Callable[[], Coroutine[Any, Any, None]]] = [lambda: keep_purging(files)]
    if settings.agents_url:
        # A deleted file's file.deleted reaches agents-service, which runs the purge workflow.
        http = httpx.AsyncClient(base_url=settings.agents_url, timeout=5)
        agents = ServiceClient.for_settings(settings, http, service="files", audience="agents", scopes=["events:emit"])
        background.append(lambda: keep_relaying(files.engine, agents))
    app = create_files_app(
        files,
        engine=files.engine,
        auth=Auth.from_settings(settings, audience="files"),
        settings=files.settings,
        background=background,
    )
    uvicorn.run(app, host=settings.bind_host, port=settings.files_port, log_config=None, access_log=False)


if __name__ == "__main__":
    main()
