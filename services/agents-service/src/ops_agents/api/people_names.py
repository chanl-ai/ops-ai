"""People's display names for lists that say who did something (c-201): startedBy on a run, actor on an Activity row.
Runs and records keep a person's email; their name is platform-service's. Read through ServiceClient once a minute per
tenant; an email whose name cannot be read is shown as the email."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.logging import get_logger

from ..store.tenancy import current_tenant

log = get_logger("ops_agents.people_names")

CACHE_SECONDS = 60.0


class PlatformPeopleNames:
    def __init__(self, platform: ServiceClient | None, clock: Callable[[], float] = time.monotonic) -> None:
        self.platform, self.clock = platform, clock
        self.cached: dict[str, tuple[dict[str, str], float]] = {}

    async def names(self, emails: set[str]) -> dict[str, str]:
        """The display name of each email the workspace knows; one missing from the cached list re-reads it."""
        if self.platform is None or not emails:
            return {}
        tenant = current_tenant()
        hit = self.cached.get(tenant)
        if hit is None or self.clock() - hit[1] >= CACHE_SECONDS or not emails <= set(hit[0]):
            try:
                rows = cast(list[dict[str, Any]], await self.platform.get("/v1/people-names") or [])
            except (ServiceCallError, ServiceUnreachable) as e:
                log.warning("people's names unread; showing their emails", extra={"error": str(e)})
                return dict(hit[0]) if hit else {}
            hit = ({str(r["email"]).lower(): str(r["name"]) for r in rows}, self.clock())
            self.cached[tenant] = hit
        return {e: hit[0][e.lower()] for e in emails if e.lower() in hit[0]}
