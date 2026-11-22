"""People's display names for lists that say who did something: startedBy on a run, actor on an Activity row.
Runs and records keep a person's email; their name is platform-service's, asked for by the emails a page shows and
kept a minute per tenant; an email whose name cannot be read is shown as the email."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.http import Json
from ops_service_kit.logging import get_logger

from ..store.tenancy import current_tenant

log = get_logger("ops_agents.people_names")

CACHE_SECONDS = 60.0


class PlatformPeopleNames:
    def __init__(self, platform: ServiceClient | None, clock: Callable[[], float] = time.monotonic) -> None:
        self.platform, self.clock = platform, clock
        # Per tenant: the names read, every email asked for (named or not, so an unknown address is not asked again
        # on each page), and when the minute began.
        self.cached: dict[str, tuple[dict[str, str], set[str], float]] = {}

    async def names(self, emails: set[str]) -> dict[str, str]:
        """The display name of each email the workspace knows; emails not asked for in the last minute are read."""
        if self.platform is None or not emails:
            return {}
        tenant = current_tenant()
        hit = self.cached.get(tenant)
        if hit is None or self.clock() - hit[2] >= CACHE_SECONDS:
            hit = (dict[str, str](), set[str](), self.clock())
            self.cached[tenant] = hit
        known, asked, _ = hit
        missing = sorted({e.lower() for e in emails} - asked)
        if missing:
            try:
                rows = cast(list[Json], await self.platform.get("/v1/people-names", params={"emails": missing}) or [])
            except (ServiceCallError, ServiceUnreachable) as e:
                log.warning("people's names unread; showing their emails", extra={"error": str(e)})
            else:
                known.update({str(r["email"]).lower(): str(r["name"]) for r in rows})
                asked.update(missing)
        return {e: known[e.lower()] for e in emails if e.lower() in known}
