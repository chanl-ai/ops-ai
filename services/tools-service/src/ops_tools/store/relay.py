"""The relay of tools-service's outbox, wired through `ops_store.outbox.relay()`: each event goes to agents-service as
this service, for the event's tenant and team, while agents-service is down it waits in the outbox and goes out once
it is back. A tool's answer changed (`policy.changed`) goes to agents-service's platform-events route, as
platform-service's does; every other event is a workflow trigger on /v1/events.

ROUTES is the one list of who hears what; both targets are agents-service, by the route each event takes."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_access.platform_events import POLICY_CHANGED
from ops_store.outbox import Poster, Relay, relay

from .modules import service_outbox
from .tenancy import SYSTEM_ROLE

PLATFORM, AGENTS = "platform_events", "agents"
ROUTES: dict[str, tuple[str, ...]] = {POLICY_CHANGED: (PLATFORM,), "*": (AGENTS,)}
PATHS = {PLATFORM: "/v1/platform-events"}
KEY = "tools_relay"


def tools_relay(engine: AsyncEngine, agents: Poster) -> Relay:
    """The outbox's relay, reading and marking every tenant's events as the system role, each posted for its own
    tenant and team."""
    targets: Mapping[str, Poster] = {PLATFORM: agents, AGENTS: agents}
    return relay(engine, service_outbox, routes=ROUTES, targets=targets, role=SYSTEM_ROLE, path_by_target=PATHS)
