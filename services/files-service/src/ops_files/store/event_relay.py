"""Delivers files-service's service events (c-258's outbox) to agents-service's POST /v1/events, as this service with
the events:emit scope, for the event's tenant and team (c-250). A deleted file's file.deleted waits in the outbox
while agents-service is down and is delivered when it is back."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_files.store.files import SYSTEM_ROLE, service_outbox
from ops_files.store.read_requests import EVENT, ReadRequestsStore
from ops_identity import ServiceClient
from ops_store.outbox import Relay, Send


def sender(agents: ServiceClient, requests: ReadRequestsStore) -> Send:
    """One event to agents-service; raises on any answer but success, so the relay tries it again later. A read
    request's event records the run it started on the request, which the console follows."""

    async def send(item: dict[str, Any]) -> None:
        body: dict[str, Any] = item["body"]
        tenant = str(item["tenantId"])
        answer: Any = await agents.post("/v1/events", body, tenant=tenant, team=str(body["teamId"]))
        if body["name"] == EVENT and isinstance(answer, dict):
            done = cast(dict[str, Any], answer)
            runs = cast(list[str], done.get("runIds") or [])
            await requests.started(str(body["key"]), status=str(done.get("status")), run_id=next(iter(runs), None))

    return send


async def keep_relaying(engine: AsyncEngine, agents: ServiceClient) -> None:
    """Until the server stops, which cancels the task."""
    relay = Relay(engine, service_outbox, sender(agents, ReadRequestsStore(engine)), role=SYSTEM_ROLE)
    await relay.run(asyncio.Event())
