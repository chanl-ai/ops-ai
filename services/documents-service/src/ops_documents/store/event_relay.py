"""Delivers documents-service's service events (extraction.*, c-258's outbox) to agents-service's POST /v1/events, as
this service with the events:emit scope, for the event's tenant and team. An event waits in the outbox while
agents-service is down and is delivered when it is back."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store.extractions import service_outbox
from ops_documents.store.metadata import SYSTEM_ROLE
from ops_identity import ServiceClient
from ops_store import background
from ops_store.outbox import Relay, Send


def sender(agents: ServiceClient) -> Send:
    """One event to agents-service; raises on any answer but success, so the relay tries it again later."""

    async def send(item: dict[str, Any]) -> None:
        body: dict[str, Any] = item["body"]
        await agents.post("/v1/events", body, tenant=str(item["tenantId"]), team=str(body["teamId"]))

    return send


async def keep_relaying(engine: AsyncEngine, agents: ServiceClient) -> None:
    """Until the server stops, which cancels the task; a failed pass is retried and shows in /health/background."""
    await Relay(engine, service_outbox, sender(agents), role=SYSTEM_ROLE).run(
        asyncio.Event(), key="documents_relay", store=background.LOCAL
    )
