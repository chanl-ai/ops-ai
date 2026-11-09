"""Delivers kb-service's outbox (kb_outbox): audit entries of settings changes to platform-service's POST
/v1/audit-events, the account's one audit log, with `audit:create`; every other event (a source that keeps failing) to
agents-service's POST /v1/events with `events:emit`, where the workflows that listen to it run. Each goes as its tenant
and team. An event waits in the outbox while its service is down and goes out once it is back."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import ServiceClient
from ops_store import background
from ops_store.audit import AUDIT_EVENT, AUDIT_ROUTE
from ops_store.outbox import Relay, Send

from .knowledge import SYSTEM_ROLE, kb_outbox

EVENTS_ROUTE = "/v1/events"


def sender(platform: ServiceClient | None, agents: ServiceClient | None) -> Send:
    """One event to its service; raises on any answer but success, so the relay tries it again. An event whose
    service this installation does not run is delivered by doing nothing: nobody would read it."""

    async def send(item: dict[str, Any]) -> None:
        body: dict[str, Any] = dict(item["body"])
        if body.get("name") == AUDIT_EVENT:
            if platform is not None:
                # The team travels in the token, never the body.
                team = str(body.pop("teamId"))
                await platform.post(AUDIT_ROUTE, body, tenant=str(item["tenantId"]), team=team)
            return
        if agents is not None:
            await agents.post(EVENTS_ROUTE, body, tenant=str(item["tenantId"]), team=str(body["teamId"]))

    return send


def relay(engine: AsyncEngine, platform: ServiceClient | None, agents: ServiceClient | None = None) -> Relay:
    return Relay(engine, kb_outbox, sender(platform, agents), role=SYSTEM_ROLE)


async def keep_relaying(
    engine: AsyncEngine, platform: ServiceClient | None, agents: ServiceClient | None, stop: asyncio.Event
) -> None:
    """Until `stop`; a failed pass is retried and shows in /health/background."""
    await relay(engine, platform, agents).run(stop, key="kb_relay", store=background.LOCAL)
