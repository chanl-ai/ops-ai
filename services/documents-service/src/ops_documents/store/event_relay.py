"""Delivers documents-service's service events (the outbox) to the services that subscribe to them, as this service
with the events:emit scope, for the event's tenant and team: extraction.* to agents-service's POST /v1/events, and
reading.finished and reading.failed to kb-service's, which indexes a file once its reading ends. An event waits in
the outbox while its subscriber is down and is delivered when it is back."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store.extractions import service_outbox
from ops_documents.store.metadata import SYSTEM_ROLE
from ops_documents.store.readings import FAILED_EVENT, FINISHED_EVENT
from ops_identity import ServiceClient
from ops_store import background
from ops_store.outbox import Relay, Send

# Which subscriber each event goes to; an event not listed goes to agents-service.
SUBSCRIBERS = {FINISHED_EVENT: "kb", FAILED_EVENT: "kb"}


def sender(agents: ServiceClient | None, kb: ServiceClient | None = None) -> Send:
    """One event to its subscriber; raises on any answer but success, so the relay tries it again later. An event
    whose subscriber this installation does not run is dropped: nobody would read it."""
    clients = {"agents": agents, "kb": kb}

    async def send(item: dict[str, Any]) -> None:
        body: dict[str, Any] = item["body"]
        client = clients[SUBSCRIBERS.get(str(body.get("name") or item.get("name") or ""), "agents")]
        if client is None:
            return
        await client.post("/v1/events", body, tenant=str(item["tenantId"]), team=str(body["teamId"]))

    return send


async def keep_relaying(engine: AsyncEngine, agents: ServiceClient | None, kb: ServiceClient | None = None) -> None:
    """Until the server stops, which cancels the task; a failed pass is retried and shows in /health/background."""
    await Relay(engine, service_outbox, sender(agents, kb), role=SYSTEM_ROLE).run(
        asyncio.Event(), key="documents_relay", store=background.LOCAL
    )
