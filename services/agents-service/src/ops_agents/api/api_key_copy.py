"""Keeps the API key copy (store/api_key_copies.py) in step with platform-service.

An `api_key.changed` event, delivered at `POST /v1/platform-events`, applies the one key it names. The resync is what
keeps the copy right while platform-service sends no such event, and repairs one the relay never delivered: it reads
`GET /v1/api-key-summaries` for each tenant this service holds agents for and makes that tenant's rows equal to it.

The copy is read before platform-service is asked and reconciled after, each in its own transaction; nothing is held
while platform-service answers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from pydantic import JsonValue, TypeAdapter

from ops_access.platform_events import Handler
from ops_service_kit.logging import get_logger
from ops_store import background, isolation
from ops_store.background import HeartbeatStore, Tx
from ops_store.database import Database

from ..store.agent_registry import AgentRegistry
from ..store.api_key_copies import API_KEY_CHANGED, RESYNC_KEY, ApiKeyCopies, KeySummary, listed_event, wired_event
from ..store.tenancy import API_KEY_RESYNC, current_tenant

log = get_logger("ops_agents.api_key_copy")
KeySummaries = TypeAdapter(list[KeySummary])

PATH = "/v1/api-key-summaries"
# The tenants a pass works: those holding agents here, read past the tenant at start (AgentRegistry).
Tenants = Callable[[], Awaitable[list[str]]]


class Getter(Protocol):
    """What the resync needs of platform-service's client (`ops_identity.ServiceClient`): a GET that mints its token
    for the current tenant (with the settings:view scope) and returns the reply's data."""

    async def get(self, path: str, **kw: Any) -> Any: ...


async def resync_tenant(copies: ApiKeyCopies, platform: Getter) -> int:
    """Makes the current tenant's copy equal to platform's list of its keys; returns how many rows changed."""
    tenant = current_tenant()
    before = await copies.held()
    listed = KeySummaries.validate_python(await platform.get(PATH) or [])
    return await copies.reconcile([listed_event(k, tenant_id=tenant) for k in listed], before)


async def resync_all(db: Database, platform: Getter, tenants: Tenants | None = None) -> int:
    """One pass over every tenant this service holds agents for, each as that tenant. A tenant that fails is logged
    and the others go on; the pass then raises the first failure, so it shows on /health/background."""
    copies = ApiKeyCopies(db)
    listed = await (tenants or _agent_tenants(db))()
    changed, failed = 0, None
    for tenant in sorted(set(listed)):
        try:
            # Left on the block's way out, so one tenant's scope never reaches the next.
            with isolation.tenant_wide(API_KEY_RESYNC, tenant_id=tenant):
                changed += await resync_tenant(copies, platform)
        except Exception as e:  # one tenant's failure must not stop the others
            log.warning("api_key_resync_failed", tenant=tenant, error=type(e).__name__)
            failed = failed or e
    if failed is not None:
        raise failed
    return changed


def _agent_tenants(db: Database) -> Tenants:
    async def read() -> list[str]:
        return [t for t, *_ in await AgentRegistry(db).published_pointers()]

    return read


async def keep_in_step(
    db: Database, platform: Getter, *, stop: asyncio.Event, beats: HeartbeatStore, tenants: Tenants | None = None
) -> None:
    """The listed resync process: a pass at start, then one every RESYNC_EVERY_S, its heartbeat on
    /health/background."""

    async def cycle(_tx: Tx, _now: float) -> int:
        return await resync_all(db, platform, tenants)

    background.give_pass(RESYNC_KEY, cycle, service="agents")
    await background.run_sweep(RESYNC_KEY, stop=stop, store=beats)


def key_changed_handler(db: Callable[[], Database]) -> dict[str, Handler]:
    """`api_key.changed` from platform-service's relay: the key's copy row, in the tenant and team the relay's token
    names."""

    async def apply(tenant: str, team_id: str, payload: Mapping[str, JsonValue]) -> int:
        return await ApiKeyCopies(db()).apply([wired_event(team_id, payload, tenant_id=tenant)])

    return {API_KEY_CHANGED: Handler("agents", "create", apply)}
