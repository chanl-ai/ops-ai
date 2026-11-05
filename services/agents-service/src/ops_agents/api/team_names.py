"""Team display names for detail responses, and the workspace's Security team, which only platform-service knows.
Read through ServiceClient once a minute per tenant; a name that cannot be read is None and the console shows the id.
The Security team decides security reviews, so one that cannot be read refuses the request rather than guess."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.errors import ServiceUnavailable
from ops_service_kit.logging import get_logger

from ..store.tenancy import current_tenant
from .deps import Runtime

log = get_logger("ops_agents.team_names")

CACHE_SECONDS = 60.0


class PlatformTeamNames:
    def __init__(self, platform: ServiceClient | None, clock: Callable[[], float] = time.monotonic) -> None:
        self.platform, self.clock = platform, clock
        self.cached: dict[str, tuple[dict[str, str], float]] = {}
        self.security: dict[str, tuple[str | None, float]] = {}

    async def name(self, team_id: str) -> str | None:
        if self.platform is None:
            return None
        tenant = current_tenant()
        hit = self.cached.get(tenant)
        if hit is None or self.clock() - hit[1] >= CACHE_SECONDS or team_id not in hit[0]:
            try:
                rows = cast(list[dict[str, Any]], await self.platform.get("/v1/team-names") or [])
            except (ServiceCallError, ServiceUnreachable) as e:
                log.warning("team names unread; showing the id", extra={"error": str(e)})
                return hit[0].get(team_id) if hit else None
            hit = ({str(r["id"]): str(r["name"]) for r in rows}, self.clock())
            self.cached[tenant] = hit
        return hit[0].get(team_id)

    async def security_team(self) -> str | None:
        """The workspace's Security team from its record (Settings > Workspace); None when it names none."""
        if self.platform is None:
            return None
        tenant = current_tenant()
        hit = self.security.get(tenant)
        if hit is None or self.clock() - hit[1] >= CACHE_SECONDS:
            try:
                found = cast(dict[str, Any], await self.platform.get("/v1/settings/workspace-teams") or {})
            except (ServiceCallError, ServiceUnreachable) as e:
                if hit is not None:
                    return hit[0]
                raise ServiceUnavailable(
                    "The workspace's Security team cannot be read now; try again.", code="security_team_unavailable"
                ) from e
            hit = (str(found.get("securityTeam") or "") or None, self.clock())
            self.security[tenant] = hit
        return hit[0]


async def security_team(rt: Runtime) -> str | None:
    """The workspace's Security team, which decides security reviews; None without platform-service (dev)."""
    names = cast(PlatformTeamNames | None, getattr(rt, "team_names", None))
    return await names.security_team() if names is not None else None


async def team_name(rt: Runtime, team_id: str | None) -> dict[str, str | None]:
    """`{"teamName": ...}` for a detail response; None without a platform URL or a team."""
    names = cast(PlatformTeamNames | None, rt.team_names)
    return {"teamName": await names.name(team_id) if names is not None and team_id else None}


async def deciding_team(rt: Runtime, team_id: str | None) -> dict[str, str | None] | None:
    """`{"id", "name"}` of the team that decides a review, so a task says who decides it by name; the name is None
    when it cannot be read (or a runtime reads no names) and the console shows the id. None for no team."""
    if not team_id:
        return None
    names = cast(PlatformTeamNames | None, getattr(rt, "team_names", None))
    return {"id": team_id, "name": await names.name(team_id) if names is not None else None}
