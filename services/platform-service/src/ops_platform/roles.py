"""Roles and what a person may do: the decisions behind the read-only role routes, with storage behind `RoleStore`.

Every signed-in person reads the roles and their grids, as every member reads Access today. A person reads their own
permissions in every team; another person's only in the teams both belong to, and a person who shares no team with
the caller is not found, so the route cannot be used to list who exists elsewhere in the tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NotRequired, TypedDict

from ops_access import (
    ACTIONS,
    ANY_TEAM,
    AREAS,
    BUILTIN_GRIDS,
    SECURITY_TEAM_ACTIONS,
    SELF_APPROVAL,
    Grant,
    Granted,
    effective,
)
from ops_access.catalogue import ADMIN, FIXED_ROLES
from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_service_kit.http import Json
from ops_service_kit.ids import now_iso
from ops_service_kit.listing import ListParams
from ops_store.listing import ListPage

from .store.roles import (
    AlreadyGrantedError,
    Holdings,
    PrivilegedForGroupError,
    RoleInUseError,
    RoleNameTakenError,
    RoleRow,
    RoleStore,
    UnknownGroupError,
)

# Approvals · decide (SELF_APPROVAL) is "approve own requests": a role holds it only where someone ticked it, so a copy
# leaves it out and the new role gains it only with its own audited tick.


def _not_copied(area: str, action: str) -> bool:
    return custom_role_refuses(area, action) or (area, action) == SELF_APPROVAL


class Cell(TypedDict):
    area: str
    action: str
    scope: str


class GridRow(TypedDict):
    area: str
    # Every action in the catalogue: the scope this role grants it, or None.
    actions: dict[str, str | None]


class RoleView(TypedDict):
    """One role as `RoleDetail` sends it; the routes add `canEdit`, and a created role names the cells it left out."""

    id: str
    name: str
    builtin: bool
    description: str
    assignmentCount: int
    permissionCount: int
    permissions: list[Cell]
    grid: list[GridRow]
    notHeld: list[str]
    leftOut: NotRequired[list[str]]
    canEdit: NotRequired[bool]


class EffectiveCell(TypedDict):
    area: str
    action: str
    scope: str
    securityTeamOnly: bool
    roles: list[dict[str, str]]


class TeamCells(TypedDict):
    teamId: str
    teamName: str
    permissions: list[EffectiveCell]


# Transfers, closes and restores the workspace: on Owner and no other role, moved only by a transfer (E42).
OWNER_CELL = ("workspace", "manage")


class PermissionsView(TypedDict):
    """What a person may do, as `PermissionsOut` sends it; the person route adds their name and address."""

    workspace: list[EffectiveCell]
    personId: str
    permissionVersion: int
    teams: list[TeamCells]
    name: NotRequired[str]
    email: NotRequired[str]


def custom_role_refuses(area: str, action: str) -> bool:
    """D40: a custom role holds no secrets or egress cell and no Security-team cell, which only the built-in roles
    give; nor `workspace.manage`, which only Owner holds (E42)."""
    return area == "secrets_egress" or (area, action) in SECURITY_TEAM_ACTIONS or (area, action) == OWNER_CELL


def _checked(cells: list[Grant]) -> None:
    for area, action, scope in cells:
        if area not in AREAS or action not in ACTIONS or scope not in ("all", "own"):
            raise ValidationFailed(f"{area}.{action} ({scope}) is not a permission.", code="unknown_cell")


@dataclass
class Roles:
    store: RoleStore

    async def list(self, tenant_id: str, params: ListParams) -> ListPage:
        return await self.store.roles(tenant_id, params)

    async def get(self, tenant_id: str, role_id: str) -> RoleView:
        role = await self.store.role_by_id(tenant_id, role_id)
        if role is None:
            raise NotFound("No role with that id.")
        grants = role.grants
        held = {(a, x): s for a, x, s in grants}
        return {
            "id": role.id,
            "name": role.name,
            "builtin": role.builtin,
            "description": role.description,
            "assignmentCount": role.assignment_count,
            "permissionCount": len(grants),
            "permissions": [{"area": a, "action": x, "scope": s} for a, x, s in grants],
            # The whole catalogue, one row per area, so a grid shows refused cells as well as granted ones.
            "grid": [
                {"area": area, "actions": {action: held.get((area, action)) for action in ACTIONS}} for area in AREAS
            ],
            # The cells a custom role may never hold: secrets, egress, Security-team and Owner ones (D40, E42).
            "notHeld": []
            if role.builtin
            else [f"{a}.{x}" for a in AREAS for x in ACTIONS if custom_role_refuses(a, x)],
        }

    async def edit(self, tenant_id: str, role_id: str, cells: list[Grant], *, by: str, request_id: str) -> RoleView:
        """Sets a role's cells, built-in or custom. Admin keeps every cell: 409 `admin_holds_every_cell`; Owner and
        Security admin are not edited either (`FIXED_ROLES`), 409 `role_set_by_rule`, refused before the cells are
        read so an empty list is refused too. A cell outside the catalogue is 400 `unknown_cell`; `workspace.manage`
        on another built-in role is 400 `owner_only`; an empty list on any other built-in role is 400
        `builtin_role_empty` (reset puts it back to its seed).
        The caller's right to change roles is checked by the route."""
        if role_id == ADMIN.id:
            raise Conflict("Admin holds every permission in its team; it is not edited.", code="admin_holds_every_cell")
        if role_id in FIXED_ROLES:
            raise Conflict(
                "Owner and Security admin come with the workspace's owner and the Security team's admins; their "
                "permissions are not edited.",
                code="role_set_by_rule",
            )
        _checked(cells)
        role = await self.store.role_by_id(tenant_id, role_id)
        if role is not None and role.builtin and not cells:
            # A built-in role with no rows reads as its seed, so an empty list would remove nothing.
            raise ValidationFailed(
                "A built-in role keeps at least one permission; reset it to go back to the cells it ships with.",
                code="builtin_role_empty",
            )
        if role is not None and not role.builtin:
            self._custom_cells(cells)
        elif any((a, x) == OWNER_CELL for a, x, _ in cells):
            raise ValidationFailed(
                "Only Owner holds workspace.manage; it moves from person to person by a transfer.",
                code="owner_only",
                details={"cells": ["workspace.manage"]},
            )
        if not await self.store.set_grid(tenant_id, role_id, cells, by=by, request_id=request_id, action="role.edit"):
            raise NotFound("No role with that id.")
        return await self.get(tenant_id, role_id)

    def _custom_cells(self, cells: list[Grant]) -> None:
        refused = sorted(f"{a}.{x}" for a, x, _ in cells if custom_role_refuses(a, x))
        if refused:
            raise ValidationFailed(
                f"A custom role cannot hold {', '.join(refused)}: secrets, egress and Security-team permissions come "
                "only with a built-in role, and workspace.manage only with Owner.",
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
    ) -> RoleView:
        """A custom role: from `cells`, or a copy of `copy_of`'s cells less those a custom role may not hold and less
        "approve own requests" (both named in `leftOut`), or empty. 409 `name_taken` for a name another role has."""
        left_out: list[str] = []
        if copy_of is not None:
            source = await self.store.role_by_id(tenant_id, copy_of)
            if source is None:
                raise NotFound("No role with that id to copy.")
            grants: list[Grant] = list(source.grants)
            left_out = sorted(f"{a}.{x}" for a, x, _ in grants if _not_copied(a, x))
            grants = [g for g in grants if not _not_copied(g[0], g[1])]
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
        made = await self.get(tenant_id, role_id)
        made["leftOut"] = left_out
        return made

    async def rename(
        self, tenant_id: str, role_id: str, *, name: str, description: str | None, by: str, request_id: str
    ) -> RoleView:
        role = await self._custom(tenant_id, role_id, "renamed")
        try:
            await self.store.rename(
                tenant_id, role.id, name=name, description=description, by=by, request_id=request_id
            )
        except RoleNameTakenError as e:
            raise Conflict(f"A role named {name} exists already.", code="name_taken") from e
        return await self.get(tenant_id, role_id)

    async def delete(self, tenant_id: str, role_id: str, *, move_to: str | None, by: str, request_id: str) -> int:
        """409 `role_in_use` naming the holders while anyone holds it, unless `move_to` names the role they move to."""
        await self._custom(tenant_id, role_id, "deleted")
        if move_to is not None and (move_to == role_id or await self.store.role_by_id(tenant_id, move_to) is None):
            raise ValidationFailed("Move the holders to another role of this workspace.", code="move_to_unknown")
        try:
            return await self.store.delete(tenant_id, role_id, move_to=move_to, by=by, request_id=request_id)
        except RoleInUseError as e:
            names = ", ".join(sorted({h.name for h in e.holders}))
            raise Conflict(
                f"{names} hold this role. Move them to another role, or delete it moving them.",
                code="role_in_use",
                details={"holders": [h.model_dump(by_alias=True) for h in e.holders]},
            ) from e

    async def grant(
        self, tenant_id: str, person_id: str, role_id: str, team_id: str, *, by: str, request_id: str
    ) -> Json:
        """Gives a person a custom role in a team they belong to. A built-in role comes with their team role instead
        (409 `builtin_role`); 409 `not_a_member` outside their teams, `already_granted` when they hold it there."""
        role = await self.store.role_by_id(tenant_id, role_id)
        if role is None:
            raise NotFound("No role with that id.")
        if role.builtin:
            raise Conflict(
                f"{role.name} comes with a person's team role; change their role in the team instead.",
                code="builtin_role",
            )
        if team_id not in (await self.store.holdings(tenant_id, person_id)).teams:
            raise Conflict("Add the person to the team before giving them a role there.", code="not_a_member")
        try:
            grant_id = await self.store.grant(tenant_id, person_id, role_id, team_id, by=by, request_id=request_id)
        except AlreadyGrantedError as e:
            raise Conflict(f"They hold {role.name} in that team already.", code="already_granted") from e
        [given] = (await self.store.grants_of(tenant_id, person_id, ListParams(ids=[grant_id])))["data"]
        return given

    async def give(
        self, tenant_id: str, role_id: str, kind: str, subject_id: str, team_id: str, *, by: str, request_id: str
    ) -> Json:
        """Gives a person or a group a custom role in a team, from the role's page, and answers the new holder row. A
        person goes through `grant` (its 409s apply); a group the workspace lacks is 404, and a group is never given a
        role holding a privileged cell (409 `privileged_for_group` naming the cells) or one it holds (409
        `already_granted`). The store writes the `role.grant` audit entry either way."""
        if kind == "person":
            await self.grant(tenant_id, subject_id, role_id, team_id, by=by, request_id=request_id)
        else:
            role = await self._custom(tenant_id, role_id, "given to a group")
            try:
                await self.store.assign(
                    tenant_id, subject_kind="group", subject_id=subject_id, role_id=role_id, team_id=team_id, by=by,
                    request_id=request_id,
                )  # fmt: skip
            except UnknownGroupError as e:
                raise NotFound("No group with that id.") from e
            except PrivilegedForGroupError as e:
                raise Conflict(
                    f"{role.name} holds permissions a group is never given: {', '.join(e.cells)}. "
                    "Give it to each person.",
                    code="privileged_for_group",
                    details={"cells": e.cells},
                ) from e
            except AlreadyGrantedError as e:
                raise Conflict(f"That group holds {role.name} in this team already.", code="already_granted") from e
        rows = (await self.store.holders(tenant_id, role_id, ListParams(ids=[subject_id])))["data"]
        return next(r for r in rows if r["kind"] == kind and r["teamId"] == team_id)

    async def _custom(self, tenant_id: str, role_id: str, verb: str) -> RoleRow:
        role = await self.store.role_by_id(tenant_id, role_id)
        if role is None:
            raise NotFound("No role with that id.")
        if role.builtin:
            raise Conflict(f"A built-in role is not {verb}; copy it to make your own.", code="builtin_role")
        return role

    async def reset(self, tenant_id: str, role_id: str, *, by: str, request_id: str) -> RoleView:
        """Puts a built-in role back to the cells it ships with; a custom role has none to go back to (400
        `not_builtin`)."""
        seed = BUILTIN_GRIDS.get(role_id)
        if seed is None:
            raise ValidationFailed("Only a built-in role has a default to go back to.", code="not_builtin")
        if role_id == ADMIN.id:
            raise Conflict("Admin holds every permission in its team; it is not edited.", code="admin_holds_every_cell")
        await self.store.set_grid(tenant_id, role_id, list(seed), by=by, request_id=request_id, action="role.reset")
        return await self.get(tenant_id, role_id)

    async def of_me(self, tenant_id: str, user_id: str) -> PermissionsView:
        mine = await self.store.holdings(tenant_id, user_id)
        grids, security, version = await self._view_inputs(tenant_id, mine)
        return permissions_view(user_id, mine, grids, security=security, version=version, teams=None)

    async def of_person(self, tenant_id: str, caller_id: str, person_id: str) -> PermissionsView:
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
        grids, security, version = await self._view_inputs(tenant_id, person)
        return permissions_view(person_id, person, grids, security=security, version=version, teams=shared)

    async def _view_inputs(self, tenant_id: str, h: Holdings) -> tuple[dict[str, list[Grant]], str | None, int]:
        """The grids of the roles `h` holds, the workspace's Security team and its permission version."""
        grids = await self.store.grids(tenant_id, sorted({a.role_id for a in h.assignments}))
        return grids, await self.store.security_team(tenant_id), await self.store.version(tenant_id)


def permissions_view(
    person_id: str,
    h: Holdings,
    grids: dict[str, list[Grant]],
    *,
    security: str | None,
    version: int,
    teams: list[str] | None,
) -> PermissionsView:
    """What a person may do, per team and in every team, from their holdings and the grids of the roles they hold: what
    `/v1/me/permissions` answers. `teams` limits the answer to those teams; None shows every team the person belongs to
    or is assigned in."""
    assignments = h.assignments if teams is None else [a for a in h.assignments if a.team_id in (*teams, ANY_TEAM)]
    per_team = effective(assignments, grids, teams if teams is not None else list(h.teams), now_iso())
    if teams is not None:
        per_team = {t: v for t, v in per_team.items() if t in teams}
    # A Security-team action is decided in the workspace's Security team whatever team a request acts in, so a
    # grid cell for it in any other team grants nothing and is not listed there; with no Security team named,
    # nobody holds it.
    per_team = {
        t: {cell: g for cell, g in held.items() if t == security or cell not in SECURITY_TEAM_ACTIONS}
        for t, held in per_team.items()
    }
    order = {(a, x): (AREAS.index(a), ACTIONS.index(x)) for a in AREAS for x in ACTIONS}
    # What the person may do in every team at once: their `*` assignments only (a workspace admin).
    every = [a for a in assignments if a.team_id == ANY_TEAM]
    workspace = effective(every, grids, [ANY_TEAM], now_iso()).get(ANY_TEAM, {}) if every else {}

    def rows(held: dict[tuple[str, str], Granted]) -> list[EffectiveCell]:
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
        "permissionVersion": version,
        "teams": [
            {
                "teamId": team,
                "teamName": h.teams.get(team, team),
                "permissions": rows(held),
            }
            for team, held in per_team.items()
        ],
    }
