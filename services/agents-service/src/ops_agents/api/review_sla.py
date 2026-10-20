"""How long a publish review may wait before it is overdue: the tenant's `reviewSlaHours` policy (platform, Govern >
Policies), 8 hours when it is not set or cannot be read. Read once a minute per tenant, so a list of reviews makes one
read, not one per row."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.logging import get_logger

from ..store.tenancy import current_tenant
from .deps import Runtime

log = get_logger("ops_agents.review_sla")

POLICY = "reviewSlaHours"
DEFAULT_HOURS = 8.0
CACHE_SECONDS = 60.0


class ReviewSla(Protocol):
    async def hours(self) -> float:
        """The current tenant's review deadline in hours."""
        ...


class PlatformReviewSla:
    """Reads the policy from platform-service through `ServiceClient` for the current tenant; with no client (no service
    signing key) the default holds."""

    def __init__(self, platform: ServiceClient | None, clock: Callable[[], float] = time.monotonic):
        self.platform, self.clock = platform, clock
        self.cached: dict[str, tuple[float, float]] = {}

    async def hours(self) -> float:
        tenant = current_tenant()
        hit = self.cached.get(tenant)
        if hit is not None and self.clock() - hit[1] < CACHE_SECONDS:
            return hit[0]
        if self.platform is None:
            return DEFAULT_HOURS
        try:
            value: Any = cast(dict[str, Any], await self.platform.get(f"/v1/policies/{POLICY}") or {}).get("value")
        except (ServiceCallError, ServiceUnreachable) as e:
            log.warning("review deadline policy unread; using the default", extra={"error": str(e)})
            return DEFAULT_HOURS
        # A boolean is a switch policy, not a number of hours (bool is an int in Python).
        hours = float(value) if isinstance(value, int | float) and not isinstance(value, bool) and value > 0 else None
        self.cached[tenant] = (hours or DEFAULT_HOURS, self.clock())
        return hours or DEFAULT_HOURS


async def sla_hours(rt: Runtime) -> float:
    """The deadline review views count down from; the default when no policy reader is wired (no platform URL)."""
    reader = getattr(rt, "review_sla", None)  # a runtime built without one (a worker-side or test runtime)
    return await reader.hours() if reader is not None else DEFAULT_HOURS
