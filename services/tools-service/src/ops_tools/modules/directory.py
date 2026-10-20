"""What the registry reads but does not own: teams, workflows and sample run contexts.

Teams belong to platform-service and workflows to agents-service. Until platform-service serves teams, a dev
tools-service reads them from the console seed, so the console sees the same records on the mock and on this service.
Team scoping follows the console's mock (apps/console/src/lib/api/mock/teams.ts): an all-scope team sees every module,
an owned team sees modules whose owner group is one of its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ops_service_kit.errors import Forbidden


@dataclass(frozen=True)
class Team:
    id: str
    name: str
    owner_groups: tuple[str, ...]
    scope: str


@dataclass(frozen=True)
class Directory:
    """Teams from the dev seed. Workflows are agents-service's (`workflows.WorkflowDirectory`); connections are
    tools-service's own records (`store.connections`, c-330)."""

    teams: tuple[Team, ...]

    @classmethod
    def from_seed(cls, seed: dict[str, Any], now: datetime) -> Directory:
        return cls(teams=tuple(Team(t["id"], t["name"], tuple(t["ownerGroups"]), t["scope"]) for t in seed["teams"]))

    @property
    def wide_teams(self) -> frozenset[str]:
        """The all-scope teams: they see every team's records, and their connections serve every team (c-330)."""
        return frozenset(t.id for t in self.teams if t.scope == "all")

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

    def owners(self, m: Mapping[str, Any]) -> list[str | None]:
        """A module's owner group and those of the teams owning the workflows it is approved for, as each approval
        recorded them when it was requested (the workflow's team comes from agents-service, c-039)."""
        groups: list[str | None] = [m["owner_team"]]
        for a in m["approvals"]:
            team = self.team_by_id(a.get("workflow_team_id"))
            groups.extend(team.owner_groups if team else [])
        return groups

    def sees_module(self, team: Team, m: Mapping[str, Any]) -> bool:
        return self.sees(team, self.owners(m))

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
