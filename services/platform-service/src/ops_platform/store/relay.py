"""The relay of platform-service's outbox, wired through `ops_store.outbox.relay()`: each event goes to every service
that acts on it, at that service's POST /v1/platform-events, as this service, for the event's tenant and team. An event
waits in the outbox while a subscriber is down and goes out once it is back; a subscriber acts idempotently, since
delivery is at least once and a failed delivery to one subscriber sends the event to all of them again.

ROUTES is the one list of who hears what: a new event is a row here and a handler in each subscriber."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_access.platform_events import POLICY_CHANGED, TEAM_CREATED
from ops_store.outbox import Poster, Relay, relay

from .key_events import API_KEY_CHANGED
from .members import MEMBER_REMOVED
from .tables import platform_outbox
from .tenancy import ROLE

# An event nobody subscribes to, or whose subscriber this install does not run, is delivered by doing nothing.
ROUTES: dict[str, tuple[str, ...]] = {
    MEMBER_REMOVED: ("tools",),
    TEAM_CREATED: ("tools", "agents", "models"),
    POLICY_CHANGED: ("agents",),
    API_KEY_CHANGED: ("agents",),
}
# The rights a subscriber checks before acting on each event; the relay's token for that service carries them.
SCOPES: dict[str, list[str]] = {
    "tools": ["connections:delete", "tools:create"],
    "agents": ["agents:create"],
    "models": ["settings:manage"],
}
ROUTE = "/v1/platform-events"


def platform_relay(engine: AsyncEngine, targets: Mapping[str, Poster]) -> Relay:
    """The outbox's relay, read and marked as this service's role, each event posted for its own tenant and team."""
    return relay(engine, platform_outbox, routes=ROUTES, targets=targets, role=ROLE, path=ROUTE)
