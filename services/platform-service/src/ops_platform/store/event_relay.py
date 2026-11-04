"""Delivers platform-service's events (on the outbox) to every service that acts on each, at that
service's POST /v1/platform-events, as this service, for the event's tenant and team. An event waits in the outbox
while a subscriber is down and goes out once it is back; a subscriber acts idempotently, since delivery is at least
once and a failed delivery to one subscriber sends the event to all of them again.

SUBSCRIBERS is the one list of who hears what: a new event is a row here and a handler in each subscriber."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_access.platform_events import TEAM_CREATED
from ops_identity import ServiceClient
from ops_store import background
from ops_store.outbox import Relay, Send

from .members import MEMBER_REMOVED
from .tables import platform_outbox
from .tenancy import ROLE

SUBSCRIBERS: dict[str, tuple[str, ...]] = {MEMBER_REMOVED: ("tools",), TEAM_CREATED: ("tools", "agents")}
# The rights a subscriber checks before acting on each event; the relay's token for that service carries them.
SCOPES: dict[str, list[str]] = {"tools": ["connections:delete", "tools:create"], "agents": ["agents:create"]}
ROUTE = "/v1/platform-events"


def sender(clients: Mapping[str, ServiceClient]) -> Send:
    """One event to each service that acts on it; raises when any delivery fails, so the relay tries it again later.
    An event nobody subscribes to, or whose subscriber this install does not run, is delivered by doing nothing."""

    async def send(item: dict[str, Any]) -> None:
        body: dict[str, Any] = item["body"]
        for service in SUBSCRIBERS.get(str(body["name"]), ()):
            if (client := clients.get(service)) is not None:
                await client.post(ROUTE, body, tenant=str(item["tenantId"]), team=str(body["teamId"]))

    return send


async def keep_relaying(engine: AsyncEngine, clients: Mapping[str, ServiceClient]) -> None:
    """Until the server stops, which cancels the task; a failed pass is retried and shows in /health/background."""
    await Relay(engine, platform_outbox, sender(clients), role=ROLE).run(
        asyncio.Event(), key="platform_relay", store=background.LOCAL
    )
