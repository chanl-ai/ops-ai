"""How many agents name each model alias. agents-service owns agents, so models-service asks its
`/v1/model-alias-uses` as a service holding `agents:view` for the tenant, and keeps nothing.

`AliasUsers` is the port; `AgentsAliasUsers` is the agents-service adapter. Without an agents-service address
(`OPS_AGENTS_URL` unset), or when it does not answer, every count is None: the alias list still serves, and a reader
sees "not known" rather than a 0 that would read as safe to re-point or retire."""

from __future__ import annotations

from typing import Protocol, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.http import Json
from ops_service_kit.logging import get_logger

log = get_logger(__name__)


class AliasUsers(Protocol):
    async def counts(self, tenant_id: str, aliases: list[str]) -> dict[str, int | None]:
        """For each alias name, how many of the tenant's agents name it; None when that is not known."""
        ...


class NoAliasUsers:
    """No agents-service to ask: every count is unknown."""

    async def counts(self, tenant_id: str, aliases: list[str]) -> dict[str, int | None]:
        return dict.fromkeys(aliases)


class AgentsAliasUsers:
    def __init__(self, agents: ServiceClient) -> None:
        self.agents = agents

    async def counts(self, tenant_id: str, aliases: list[str]) -> dict[str, int | None]:
        if not aliases:
            return {}
        try:
            found = cast(
                Json,
                await self.agents.get("/v1/model-alias-uses", tenant=tenant_id, params={"aliases": ",".join(aliases)}),
            )
        except (ServiceCallError, ServiceUnreachable) as e:
            log.warning("alias_users_unavailable", error=str(e))
            return dict.fromkeys(aliases)
        return {a: n if isinstance(n := found.get(a), int) else None for a in aliases}
