"""What the registry reads but does not own: teams, workflows, connections and sample run contexts.

Teams belong to platform-service, workflows to agents-service and connections to the integrations area. Until those
serve them, a dev tools-service reads them from the console seed, so the console sees the same records on the mock
and on this service. Team scoping follows the console's mock (apps/console/src/lib/api/mock/teams.ts): an all-scope
team sees every module, an owned team sees modules whose owner group is one of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ops_service_kit.errors import Forbidden

EXPIRING = timedelta(days=30)


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    owner_groups: tuple[str, ...]
    scope: str


@dataclass(frozen=True)
class Connection:
    id: str
    name: str
    kind: str
    base: str
    auth_method: str
    catalog_id: str
    expires_at: datetime | None

    def status(self, now: datetime) -> str:
        if self.base in ("draft", "revoked", "error"):
            return self.base
        left = self.expires_at - now if self.expires_at else None
        if self.base == "needs_reconnect" or (left is not None and left < timedelta(0)):
            return "needs_reconnect"
        return "expiring" if left is not None and left < EXPIRING else "healthy"

    def ref(self, now: datetime) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "name": self.name, "kind": self.kind, "status": self.status(now)}
        if self.expires_at:
            out["expiresAt"] = self.expires_at.isoformat()
        return out

    @property
    def credential_kind(self) -> str:
        return {"api_key": "api_key", "mtls": "mtls"}.get(self.auth_method, "oauth_client_credentials")


@dataclass(frozen=True)
class Directory:
    """Teams and connections from the dev seed. Workflows are agents-service's (`workflows.WorkflowDirectory`)."""

    teams: tuple[Team, ...]
    connections: dict[str, Connection]

    @classmethod
    def from_seed(cls, seed: dict[str, Any], now: datetime) -> Directory:
        return cls(
            teams=tuple(Team(t["id"], t["name"], tuple(t["ownerGroups"]), t["scope"]) for t in seed["teams"]),
            connections={
                c["id"]: Connection(
                    id=c["id"],
                    name=c["name"],
                    kind=c["kind"],
                    base=c["base"],
                    auth_method=c["authMethod"],
                    catalog_id=c["catalogId"],
                    expires_at=now + timedelta(days=c["expiresIn"]) if c.get("expiresIn") is not None else None,
                )
                for c in seed["connections"]
            },
        )

    @property
    def everyone(self) -> Team:
        return next(t for t in self.teams if t.scope == "all")

    def team(self, team_id: str | None) -> Team:
        """The caller's team; an unknown or missing id falls to the all-scope team, as the console's team context
        does."""
        return next((t for t in self.teams if t.id == team_id), self.everyone)

    def team_of_owner(self, owner: str | None) -> Team:
        return next((t for t in self.teams if t.scope == "owned" and owner in t.owner_groups), self.everyone)

    def sees(self, team: Team, owners: list[str | None]) -> bool:
        return team.scope == "all" or any(o in team.owner_groups for o in owners if o)

    def guard(self, team: Team, owners: list[str | None], what: str) -> None:
        """403 naming the owning team when the record is outside the caller's team."""
        if self.sees(team, owners):
            return
        owned = [self.team_of_owner(o) for o in owners if o]
        owner = next((t for t in owned if t.scope == "owned"), self.everyone)
        raise Forbidden(f"This {what} belongs to {owner.name}.", details={"team": {"id": owner.id, "name": owner.name}})

    def owner_group(self, team: Team) -> str | None:
        """The owner group a record created inside `team` gets; None for the all-scope team."""
        return None if team.scope == "all" else team.owner_groups[0]

    def team_by_id(self, team_id: str | None) -> Team | None:
        """The team with this id, or None: unlike `team`, an unknown id is not anyone's, so callers fail closed."""
        return next((t for t in self.teams if t.id == team_id), None)
