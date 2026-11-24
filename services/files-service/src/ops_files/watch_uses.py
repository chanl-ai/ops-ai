# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Which workflows use a watch: agents-service's `GET /v1/watch-uses`, asked as files-service with `workflows:view`,
so the Watched folders list says a folder is in use and Stop watching is refused while a workflow names it."""

from __future__ import annotations

from typing import Protocol, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.http import JsonValue

Used = dict[str, list[dict[str, JsonValue]]]


class WatchUses(Protocol):
    async def of(self, tenant: str, team: str, ids: list[str]) -> Used | None:
        """{watch id: [{workflowId, name, live}]} for each of `ids`; None when agents-service cannot be asked."""
        ...


class AgentsWatchUses:
    """`WatchUses` over agents-service; at most 100 ids an ask, as the route takes."""

    def __init__(self, agents: ServiceClient) -> None:
        self.agents = agents

    async def of(self, tenant: str, team: str, ids: list[str]) -> Used | None:
        found: Used = {}
        for start in range(0, len(ids), 100):
            part = ids[start : start + 100]
            try:
                data = await self.agents.request(
                    "GET", "/v1/watch-uses", params={"watchIds": part}, tenant=tenant, team=team
                )
            except (ServiceCallError, ServiceUnreachable):
                return None
            answer = cast(dict[str, JsonValue], data) if isinstance(data, dict) else {}
            for i in part:
                rows = answer.get(i)
                found[i] = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        return found


__all__ = ["AgentsWatchUses", "Used", "WatchUses"]
