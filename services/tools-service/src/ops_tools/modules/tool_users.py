"""Which of a team's agents and workflows use each tool. agents-service owns agents and workflows, so tools-service
asks its `/v1/tool-uses` as a service holding `agents:view` for the caller's team, and keeps nothing.

`ToolUsers` is the port; `AgentsToolUsers` is the agents-service adapter and `StaticToolUsers` a fixed answer for
tests. When agents-service cannot answer the call fails: turning an app off on an empty "used by" would stop agents
nobody was warned about."""

from __future__ import annotations

from typing import Any, Protocol, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.errors import ServiceUnavailable

Uses = dict[str, list[dict[str, str]]]


class ToolUsers(Protocol):
    async def of(self, tenant_id: str, team_id: str, tools: list[str]) -> Uses:
        """For each tool name, its users in the team, each `{kind: agent|workflow, id, name}`."""
        ...

    async def accounts(self, tenant_id: str, team_id: str, app: str, name: str) -> dict[str, Any]:
        """The team's definitions naming the account `name` of `app`: `{drafts, published, workflows, agents}`."""
        ...


class AgentsToolUsers:
    def __init__(self, agents: ServiceClient) -> None:
        self.agents = agents

    async def of(self, tenant_id: str, team_id: str, tools: list[str]) -> Uses:
        if not tools:
            return {}
        try:
            found = await self.agents.get(
                "/v1/tool-uses", tenant=tenant_id, team=team_id, params={"tools": ",".join(tools)}
            )
        except (ServiceCallError, ServiceUnreachable) as e:
            raise ServiceUnavailable(
                "agents-service did not say which agents use these tools; try again shortly.",
                code="tool_users_unavailable",
            ) from e
        return {str(k): list(v) for k, v in cast(dict[str, Any], found).items()}

    async def accounts(self, tenant_id: str, team_id: str, app: str, name: str) -> dict[str, Any]:
        try:
            found = await self.agents.get(
                "/v1/account-uses", tenant=tenant_id, team=team_id, params={"app": app, "name": name}
            )
        except (ServiceCallError, ServiceUnreachable) as e:
            raise ServiceUnavailable(
                "agents-service did not say which workflows and agents name this account; try again shortly.",
                code="account_users_unavailable",
            ) from e
        return dict(cast(dict[str, Any], found))


class StaticToolUsers:
    """A fixed answer, for tests that do not run agents-service."""

    def __init__(self, uses: Uses | None = None) -> None:
        self.uses: Uses = uses or {}
        # By (app id, case-folded account name).
        self.account_uses: dict[tuple[str, str], dict[str, Any]] = {}

    async def of(self, tenant_id: str, team_id: str, tools: list[str]) -> Uses:
        return {t: self.uses.get(t, []) for t in tools}

    async def accounts(self, tenant_id: str, team_id: str, app: str, name: str) -> dict[str, Any]:
        none: dict[str, Any] = {"drafts": 0, "published": 0, "workflows": [], "agents": []}
        return self.account_uses.get((app, name.strip().casefold()), none)
