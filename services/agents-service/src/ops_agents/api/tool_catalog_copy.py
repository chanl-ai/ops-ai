"""Keeps the tool catalogue copy (store/tool_copies.py) in step with tools-service.

Events keep it current: `POST /v1/events` applies each `tool.module.*` and `tool.team_state.changed` it receives. The
resync carries what events cannot: a module installed at start-up with no team to route its event, a seed row at
revision 0, an event the relay never delivered. It pages `GET /v1/tool-catalog` per tenant this service holds agents
for and applies each item through the same `apply`, so a resync and an event meet on one row's revision.

A page is fetched with no transaction open, then applied in one; nothing is held while tools-service answers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from ops_service_kit.logging import get_logger
from ops_store import background, isolation
from ops_store.background import HeartbeatStore, Tx
from ops_store.database import Database

from ..store.agent_registry import AgentRegistry
from ..store.tenancy import TOOL_CATALOG_RESYNC, current_tenant
from ..store.tool_copies import RESYNC_KEY, CatalogPage, ToolCopies

log = get_logger("ops_agents.tool_catalog_copy")

PATH = "/v1/tool-catalog"
# The tenants a pass works: those holding agents here, read past the tenant at start (AgentRegistry).
Tenants = Callable[[], Awaitable[list[str]]]
# Modules per page; tools-service takes 1 to 500.
PAGE = 200


class Getter(Protocol):
    """What the resync needs of tools-service's client (`ops_identity.ServiceClient`): a GET that mints its token for
    the current tenant and returns the reply's data."""

    async def get(self, path: str, **kw: Any) -> Any: ...


async def resync_tenant(copies: ToolCopies, tools: Getter, *, page: int = PAGE) -> int:
    """Applies the current tenant's whole catalogue, page by page; returns how many events were applied."""
    tenant, after, applied = current_tenant(), None, 0
    while True:
        params = {"limit": str(page)} | ({"after": after} if after else {})
        found = CatalogPage.model_validate(await tools.get(PATH, params=params))
        if any(e.tenant_id != tenant for e in found.items):
            raise ValueError(f"tools-service answered {PATH} for another workspace than {tenant}")
        await copies.apply(found.items)
        applied += len(found.items)
        after = found.next_cursor
        if not after:
            return applied


async def resync_all(db: Database, tools: Getter, tenants: Tenants | None = None, *, page: int = PAGE) -> int:
    """One pass over every tenant this service holds agents for, each as that tenant. A tenant that fails is logged
    and the others go on; the pass then raises the first failure, so it shows on /health/background."""
    copies = ToolCopies(db)
    listed = await (tenants or _agent_tenants(db))()
    applied, failed = 0, None
    for tenant in sorted(set(listed)):
        try:
            # Left on the block's way out, so one tenant's scope never reaches the next.
            with isolation.tenant_wide(TOOL_CATALOG_RESYNC, tenant_id=tenant):
                applied += await resync_tenant(copies, tools, page=page)
        except Exception as e:  # one tenant's failure must not stop the others
            log.warning("tool_catalog_resync_failed", tenant=tenant, error=type(e).__name__)
            failed = failed or e
    if failed is not None:
        raise failed
    return applied


def _agent_tenants(db: Database) -> Tenants:
    async def read() -> list[str]:
        return [t for t, *_ in await AgentRegistry(db).published_pointers()]

    return read


async def keep_in_step(
    db: Database, tools: Getter, *, stop: asyncio.Event, beats: HeartbeatStore, tenants: Tenants | None = None
) -> None:
    """The listed resync process: a pass at start, then one every RESYNC_EVERY_S, its heartbeat on
    /health/background."""

    async def cycle(_tx: Tx, _now: float) -> int:
        return await resync_all(db, tools, tenants)

    background.give_pass(RESYNC_KEY, cycle, service="agents")
    await background.run_sweep(RESYNC_KEY, stop=stop, store=beats)
