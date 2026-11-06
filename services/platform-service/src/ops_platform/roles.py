"""Roles and what a person may do: the decisions behind the read-only role routes, with storage behind `RoleStore`.

Every signed-in person reads the roles and their grids, as every member reads Access today. A person reads their own
permissions in every team; another person's only in the teams both belong to, and a person who shares no team with
the caller is not found, so the route cannot be used to list who exists elsewhere in the tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ops_access import ACTIONS, ANY_TEAM, AREAS, BUILTIN_GRIDS, SECURITY_TEAM_ACTIONS, Grant, effective
from ops_access.catalogue import ADMIN
from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_service_kit.ids import now_iso

from .store.roles import AlreadyGrantedError, Holdings, RoleInUseError, RoleNameTakenError, RoleStore


def custom_role_refuses(area: str, action: str) -> bool:
    """D40: a custom role holds no secrets or egress cell and no Security-team cell, which only the built-in roles
    give."""
    return area == "secrets_egress" or (area, action) in SECURITY_TEAM_ACTIONS


def _checked(cells: list[Grant]) -> None:
    for area, action, scope in cells:
        if area not in AREAS or action not in ACTIONS or scope not in ("all", "own"):
            raise ValidationFailed(f"{area}.{action} ({scope}) is not a permission.", code="unknown_cell")


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
            # The cells this role may never hold: a custom role's secrets, egress and Security-team ones (D40).
            "notHeld": []
            if role["builtin"]
            else [f"{a}.{x}" for a in AREAS for x in ACTIONS if custom_role_refuses(a, x)],
        }

    async def edit(
        self, tenant_id: str, role_id: str, cells: list[Grant], *, by: str, request_id: str
    ) -> dict[str, Any]:
        """Sets a role's cells, built-in or custom. Admin keeps every cell: 409
        `admin_holds_every_cell`. A cell outside the catalogue is 400 `unknown_cell`. The caller's right to change roles
        is checked by the route."""
        if role_id == ADMIN.id:
            raise Conflict("Admin holds every permission in its team; it is not edited.", code="admin_holds_every_cell")
        _checked(cells)
        role = await self.store.role(tenant_id, role_id)
        if role is not None and not role["builtin"]:
            self._custom_cells(cells)
        if not await self.store.set_grid(tenant_id, role_id, cells, by=by, request_id=request_id, action="role.edit"):
            raise NotFound("No role with that id.")
        return await self.get(tenant_id, role_id)

    def _custom_cells(self, cells: list[Grant]) -> None:
        refused = sorted(f"{a}.{x}" for a, x, _ in cells if custom_role_refuses(a, x))
        if refused:
            raise ValidationFailed(
                f"A custom role cannot hold {', '.join(refused)}: secrets, egress and Security-team permissions come "
                "only with a built-in role.",
                code="not_for_custom_roles",
                details={"cells": refused},
            )

    async def create(
        self,
        tenant_id: str,
        *,
        name: str,
        description: str,
        copy_of: str | None,
        cells: list[Grant] | None,
        by: str,
        request_id: str,
    ) -> dict[str, Any]:
        """A custom role: from `cells`, or a copy of `copy_of`'s cells less those a custom role may not hold (named in
        `leftOut`), or empty. 409 `name_taken` for a name another role has."""
        left_out: list[str] = []
        if copy_of is not None:
            source = await self.store.role(tenant_id, copy_of)
            if source is None:
                raise NotFound("No role with that id to copy.")
            grants: list[Grant] = list(source["grants"])
            left_out = sorted(f"{a}.{x}" for a, x, _ in grants if custom_role_refuses(a, x))
            grants = [g for g in grants if not custom_role_refuses(g[0], g[1])]
        else:
            grants = list(cells or [])
            _checked(grants)
            self._custom_cells(grants)
        try:
            role_id = await self.store.create(
                tenant_id, name=name, description=description, grants=grants, by=by, request_id=request_id
            )
        except RoleNameTakenError as e:
            raise Conflict(f"A role named {name} exists already.", code="name_taken") from e
        return await self.get(tenant_id, role_id) | {"leftOut": left_out}

    async def rename(
        self, tenant_id: str, role_id: str, *, name: str, description: str | None, by: str, request_id: str
    ) -> dict[str, Any]:
        role = await self._custom(tenant_id, role_id, "renamed")
        try:
            await self.store.rename(
                tenant_id, role["id"], name=name, description=description, by=by, request_id=request_id
            )
        except RoleNameTakenError as e:
            raise Conflict(f"A role named {name} exists already.", code="name_taken") from e
        return await self.get(tenant_id, role_id)

    async def delete(self, tenant_id: str, role_id: str, *, move_to: str | None, by: str, request_id: str) -> int:
        """409 `role_in_use` naming the holders while anyone holds it, unless `move_to` names the role they move to."""
        await self._custom(tenant_id, role_id, "deleted")
        if move_to is not None and (move_to == role_id or await self.store.role(tenant_id, move_to) is None):
            raise ValidationFailed("Move the holders to another role of this workspace.", code="move_to_unknown")
        try:
            return await self.store.delete(tenant_id, role_id, move_to=move_to, by=by, request_id=request_id)
        except RoleInUseError as e:
            names = ", ".join(sorted({str(h["name"]) for h in e.holders}))
            raise Conflict(
                f"{names} hold this role. Move them to another role, or delete it moving them.",
                code="role_in_use",
                details={"holders": e.holders},
            ) from e

    async def grant(
        self, tenant_id: str, person_id: str, role_id: str, team_id: str, *, by: str, request_id: str
    ) -> dict[str, Any]:
        """Gives a person a custom role in a team they belong to. A built-in role comes with their team role instead
        (409 `builtin_role`); 409 `not_a_member` outside their teams, `already_granted` when they hold it there."""
        role = await self.store.role(tenant_id, role_id)
        if role is None:
            raise NotFound("No role with that id.")
        if role["builtin"]:
            raise Conflict(
                f"{role['name']} comes with a person's team role; change their role in the team instead.",
                code="builtin_role",
            )
        if team_id not in (await self.store.holdings(tenant_id, person_id)).teams:
            raise Conflict("Add the person to the team before giving them a role there.", code="not_a_member")
        try:
            grant_id = await self.store.grant(tenant_id, person_id, role_id, team_id, by=by, request_id=request_id)
        except AlreadyGrantedError as e:
            raise Conflict(f"They hold {role['name']} in that team already.", code="already_granted") from e
        return next(g for g in await self.store.grants_of(tenant_id, person_id) if g["id"] == grant_id)

    async def _custom(self, tenant_id: str, role_id: str, verb: str) -> dict[str, Any]:
        role = await self.store.role(tenant_id, role_id)
        if role is None:
            raise NotFound("No role with that id.")
        if role["builtin"]:
            raise Conflict(f"A built-in role is not {verb}; copy it to make your own.", code="builtin_role")
        return role

    async def reset(self, tenant_id: str, role_id: str, *, by: str, request_id: str) -> dict[str, Any]:
        """Puts a built-in role back to the cells it ships with; a custom role has none to go back to (400
        `not_builtin`)."""
        seed = BUILTIN_GRIDS.get(role_id)
        if seed is None:
            raise ValidationFailed("Only a built-in role has a default to go back to.", code="not_builtin")
        if role_id == ADMIN.id:
            raise Conflict("Admin holds every permission in its team; it is not edited.", code="admin_holds_every_cell")
        await self.store.set_grid(tenant_id, role_id, list(seed), by=by, request_id=request_id, action="role.reset")
        return await self.get(tenant_id, role_id)

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
        # A Security-team action is decided in the workspace's Security team whatever team a request acts in, so a
        # grid cell for it in any other team grants nothing and is not listed there; with no Security team named,
        # nobody holds it.
        security = await self.store.security_team(tenant_id)
        per_team = {
            t: {cell: g for cell, g in held.items() if t == security or cell not in SECURITY_TEAM_ACTIONS}
            for t, held in per_team.items()
        }
        order = {(a, x): (AREAS.index(a), ACTIONS.index(x)) for a in AREAS for x in ACTIONS}
        # What the person may do in every team at once: their `*` assignments only (a workspace admin).
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
