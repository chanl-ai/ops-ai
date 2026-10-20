"""Which agents cite each knowledge base: agents-service owns agents and their grants, so kb-service asks it.

`AgentDirectory` is the port; `AgentsUsage` asks agents-service's `/v1/knowledge-usage` with a service token holding
`agents:view` for the caller's tenant and team. Agents of the caller's team are named; others are counted, so a base
another team relies on still reads as in use. When agents-service cannot answer, usage is None ("unknown"): the list
still loads, and the console keeps the delete confirmation that a base in use asks for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Usage:
    names: list[str] = field(default_factory=list[str])
    elsewhere: int = 0


class AgentDirectory(Protocol):
    async def usage(self, tenant_id: str, team_id: str | None) -> dict[str, Usage] | None:
        """Usage by knowledge base id, or None when it cannot be known."""
        ...


class AgentsUsage:
    def __init__(self, agents: ServiceClient) -> None:
        """`agents` calls agents-service as kb-service with `agents:view`; each call names the caller's tenant and
        team, whose agents are named."""
        self.agents = agents

    async def usage(self, tenant_id: str, team_id: str | None) -> dict[str, Usage] | None:
        try:
            rows = cast(
                list[dict[str, Any]], await self.agents.get("/v1/knowledge-usage", tenant=tenant_id, team=team_id)
            )
        except (ServiceCallError, ServiceUnreachable) as e:
            log.warning("agents_usage_unavailable", error=type(e).__name__)
            return None
        return {
            str(row["kbId"]): Usage([str(a["name"]) for a in row["agents"]], int(row.get("elsewhere") or 0))
            for row in rows
        }


class StaticAgents:
    """A fixed answer, for tests that do not exercise "used by"."""

    def __init__(self, usage: dict[str, list[str]] | None = None) -> None:
        self._usage = {k: Usage(v) for k, v in (usage or {}).items()}

    async def usage(self, tenant_id: str, team_id: str | None) -> dict[str, Usage] | None:
        return self._usage
