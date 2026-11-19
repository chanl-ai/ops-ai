# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The relay of documents-service's outbox, wired through `ops_store.outbox.relay()`."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store.extractions import service_outbox
from ops_documents.store.metadata import SYSTEM_ROLE
from ops_documents.store.readings import FAILED_EVENT, FINISHED_EVENT
from ops_store.outbox import Poster, Relay, relay

# Who hears each service event: a reading's end goes to kb-service, which indexes a file once its reading ends; every
# other event (extraction.*) to agents-service. A subscriber this installation does not run is skipped.
ROUTES = {FINISHED_EVENT: ("kb",), FAILED_EVENT: ("kb",), "*": ("agents",)}


def documents_relay(engine: AsyncEngine, targets: Mapping[str, Poster]) -> Relay:
    """The outbox's relay, read and marked as the system role, each event posted for its own tenant and team."""
    return relay(engine, service_outbox, routes=ROUTES, targets=targets, role=SYSTEM_ROLE)
