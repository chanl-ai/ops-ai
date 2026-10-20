"""Delivers tools-service's service events (c-258's outbox) to agents-service's POST /v1/events, as this service with
the events:emit scope, for the event's tenant and team. Runs beside the server; an event waits in the outbox while
agents-service is down and is delivered when it is back (c-257)."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import ServiceClient
from ops_store.outbox import Relay, Send

from .modules import service_outbox


def sender(agents: ServiceClient) -> Send:
    """One event to agents-service; raises on any answer but success, so the relay tries it again later."""

    async def send(item: dict[str, Any]) -> None:
        body: dict[str, Any] = item["body"]
        await agents.post("/v1/events", body, tenant=str(item["tenantId"]), team=str(body["teamId"]))

    return send


async def keep_relaying(engine: AsyncEngine, agents: ServiceClient) -> None:
    """Until the server stops, which cancels the task."""
    await Relay(engine, service_outbox, sender(agents)).run(asyncio.Event())
