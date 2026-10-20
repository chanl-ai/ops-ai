"""Roles and what a person may do: the decisions behind the read-only role routes, with storage behind `RoleStore`.

Every signed-in person reads the roles and their grids, as every member reads Access today. A person reads their own
permissions in every team; another person's only in the teams both belong to, and a person who shares no team with
the caller is not found, so the route cannot be used to list who exists elsewhere in the tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ops_access import ACTIONS, ANY_TEAM, AREAS, SECURITY_TEAM_ACTIONS, effective
from ops_service_kit.errors import NotFound
from ops_service_kit.ids import now_iso

from .store.roles import Holdings, RoleStore


@dataclass
class Roles:
    store: RoleStore

    async def list(self, tenant_id: str) -> list[dict[str, Any]]:
        return await self.store.roles(tenant_id)

    async def get(self, tenant_id: str, role_id: str) -> dict[str, Any]:
        role = await self.store.role(tenant_id, role_id)
        if role is None:
            raise NotFound("No role with that id.")
        grants = role.pop("grants")
        held = {(a, x): s for a, x, s in grants}
        return {
            **role,
            "permissionCount": len(grants),
            "permissions": [{"area": a, "action": x, "scope": s} for a, x, s in grants],
            # The whole catalogue, one row per area, so a grid shows refused cells as well as granted ones.
            "grid": [
                {"area": area, "actions": {action: held.get((area, action)) for action in ACTIONS}} for area in AREAS
            ],
        }

    async def of_me(self, tenant_id: str, user_id: str) -> dict[str, Any]:
        mine = await self.store.holdings(tenant_id, user_id)
        return await self._view(tenant_id, user_id, mine, teams=None)

    async def of_person(self, tenant_id: str, caller_id: str, person_id: str) -> dict[str, Any]:
        if person_id == caller_id:
            return await self.of_me(tenant_id, caller_id)
        caller = await self.store.holdings(tenant_id, caller_id)
        person = await self.store.holdings(tenant_id, person_id)
        shared = [t for t in person.teams if t in caller.teams]
        # A workspace admin may do everything, reading anyone's grants included, in teams they are not in.
        if not shared and await self.store.workspace_admin(tenant_id, caller_id, now=now_iso()):
            shared = list(person.teams)
        if not shared:
            raise NotFound("No person with that id shares a team with you.")
        return await self._view(tenant_id, person_id, person, teams=shared)

    async def _view(self, tenant_id: str, person_id: str, h: Holdings, *, teams: list[str] | None) -> dict[str, Any]:
        """`teams` limits the answer to those teams; None shows every team the person belongs to or is assigned in."""
        role_ids = sorted({a.role_id for a in h.assignments})
        grids = await self.store.grids(tenant_id, role_ids)
        assignments = h.assignments if teams is None else [a for a in h.assignments if a.team_id in (*teams, ANY_TEAM)]
        per_team = effective(assignments, grids, teams if teams is not None else list(h.teams), now_iso())
        if teams is not None:
            per_team = {t: v for t, v in per_team.items() if t in teams}
        order = {(a, x): (AREAS.index(a), ACTIONS.index(x)) for a in AREAS for x in ACTIONS}
        # What the person may do in every team at once: their `*` assignments only (a workspace admin, c-198).
        every = [a for a in assignments if a.team_id == ANY_TEAM]
        workspace = effective(every, grids, [ANY_TEAM], now_iso()).get(ANY_TEAM, {}) if every else {}

        def rows(held: dict[tuple[str, str], Any]) -> list[dict[str, Any]]:
            return [
                {
                    "area": area,
                    "action": action,
                    "scope": g.scope,
                    # Held in the Security team whichever team a request acts in (SECURITY_TEAM_ACTIONS).
                    "securityTeamOnly": (area, action) in SECURITY_TEAM_ACTIONS,
                    "roles": g.roles,
                }
                for (area, action), g in sorted(held.items(), key=lambda kv: order[kv[0]])
            ]

        return {
            "workspace": rows(workspace),
            "personId": person_id,
            "permissionVersion": await self.store.version(tenant_id),
            "teams": [
                {
                    "teamId": team,
                    "teamName": h.teams.get(team, team),
                    "permissions": rows(held),
                }
                for team, held in per_team.items()
            ],
        }
