"""What still runs in a team, read from agents-service before a team is deleted or a workspace closed.

platform-service's one call to another service: `GET /v1/teams/usage` on agents-service with a service token naming
the team, which agents-service caps at `workflows:view` (Settings.service_scopes["platform"]). An answer that does not
come raises `UsageUnavailable`, and the caller refuses the action: a delete never goes ahead on an unknown answer. The
routes read the reader through `team_usage`, so a test replaces it with `app.dependency_overrides`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable


class UsageUnavailable(Exception):
    """agents-service did not answer, or answered with an error."""


@dataclass(frozen=True)
class TeamUsage:
    runs_in_progress: int
    live_workflows: list[str] = field(default_factory=list[str])


class UsageReader(Protocol):
    async def of(self, tenant_id: str, team_id: str) -> TeamUsage: ...


class _UsageReply(BaseModel):
    """agents-service's reply to `GET /v1/teams/usage`; a field it leaves out or sends as null counts as none."""

    model_config = ConfigDict(frozen=True)

    runs_in_progress: int | None = Field(None, alias="runsInProgress")
    # Any JSON value, each read as text: the names are shown, never looked up.
    live_workflows: list[Any] | None = Field(None, alias="liveWorkflows")


@dataclass
class AgentsUsage:
    """`agents` unset (no agents-service URL configured) refuses every read, so nothing is deleted unchecked."""

    agents: ServiceClient | None

    async def of(self, tenant_id: str, team_id: str) -> TeamUsage:
        if self.agents is None:
            raise UsageUnavailable("agents-service is not configured")
        try:
            reply = _UsageReply.model_validate(await self.agents.get("/v1/teams/usage", tenant=tenant_id, team=team_id))
        except (ServiceCallError, ServiceUnreachable) as e:
            raise UsageUnavailable(str(e)) from e
        except ValidationError as e:
            raise UsageUnavailable(
                f"agents-service answered usage in an unknown shape: {e.error_count()} errors"
            ) from e
        return TeamUsage(reply.runs_in_progress or 0, [str(n) for n in reply.live_workflows or []])


def team_usage(request: Request) -> UsageReader:
    return cast(UsageReader, request.app.state.team_usage)
