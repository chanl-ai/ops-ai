"""Delivers tools-service's service events (the outbox) to agents-service's POST /v1/events (policy.changed to POST
/v1/platform-events), as this service with
the events:emit scope, for the event's tenant and team. Runs beside the server; an event waits in the outbox while
agents-service is down and is delivered when it is back."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_access.platform_events import POLICY_CHANGED
from ops_identity import ServiceClient
from ops_store import background
from ops_store.outbox import Relay, Send

from .modules import service_outbox

# A tool's answer changed: agents-service hears it on its platform-events route, as it hears platform-service's
# policy.changed; every other event is a workflow trigger on /v1/events.
PLATFORM_EVENTS = {POLICY_CHANGED: "/v1/platform-events"}


def sender(agents: ServiceClient) -> Send:
    """One event to agents-service; raises on any answer but success, so the relay tries it again later."""

    async def send(item: dict[str, Any]) -> None:
        body: dict[str, Any] = item["body"]
        await agents.post(
            PLATFORM_EVENTS.get(str(body["name"]), "/v1/events"),
            body,
            tenant=str(item["tenantId"]),
            team=str(body["teamId"]),
        )

    return send


async def keep_relaying(engine: AsyncEngine, agents: ServiceClient) -> None:
    """Until the server stops, which cancels the task; a failed pass is retried and shows in /health/background."""
    await Relay(engine, service_outbox, sender(agents)).run(asyncio.Event(), key="tools_relay", store=background.LOCAL)
