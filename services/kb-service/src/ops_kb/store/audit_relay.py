"""Delivers kb-service's audit entries (kb_outbox) to platform-service's POST /v1/audit-events, the account's one
audit log, as this service with `audit:create`, for each entry's tenant and team. An entry waits in the outbox while
platform-service is down and goes out once it is back; platform-service keeps one row per entry id."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import ServiceClient
from ops_store import background
from ops_store.audit import AUDIT_ROUTE
from ops_store.outbox import Relay, Send

from .knowledge import SYSTEM_ROLE, kb_outbox


def sender(platform: ServiceClient) -> Send:
    async def send(item: dict[str, Any]) -> None:
        body: dict[str, Any] = dict(item["body"])
        # The team travels in the token, never the body.
        team = str(body.pop("teamId"))
        await platform.post(AUDIT_ROUTE, body, tenant=str(item["tenantId"]), team=team)

    return send


def relay(engine: AsyncEngine, platform: ServiceClient) -> Relay:
    return Relay(engine, kb_outbox, sender(platform), role=SYSTEM_ROLE)


async def keep_relaying(engine: AsyncEngine, platform: ServiceClient, stop: asyncio.Event) -> None:
    """Until `stop`; a failed pass is retried and shows in /health/background."""
    await relay(engine, platform).run(stop, key="kb_relay", store=background.LOCAL)
