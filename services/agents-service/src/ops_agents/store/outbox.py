"""agents-service's outbox: the audit entries of schedule changes, written in the transaction of the change and relayed
to platform-service's one audit log (ops_store.audit); read across tenants by the relay as ops_runtime_system."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store.audit import AUDIT_EVENT, AUDIT_ROUTE
from ops_store.outbox import Poster, Relay, outbox_table, relay
from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .tenancy import SYSTEM_ROLE

agents_outbox = outbox_table(metadata, "agents_outbox", info=TENANT_SCOPED)

# An audit entry goes to platform-service's account audit log (`audit:create`), its team in the token alone.
RELAY_ROUTES = {AUDIT_EVENT: ("platform",)}


def outbox_relay(engine: AsyncEngine, targets: Mapping[str, Poster]) -> Relay:
    """agents_outbox's relay to the services in `targets` ("platform"). The worker starts it only where platform-service
    has an internal endpoint, so an entry with nowhere to go waits in the table; a service left out of `targets` has
    its events marked delivered."""
    return relay(
        engine,
        agents_outbox,
        routes=RELAY_ROUTES,
        targets=targets,
        role=SYSTEM_ROLE,
        team_in_token=frozenset({"platform"}),
        path_by_target={"platform": AUDIT_ROUTE},
    )
