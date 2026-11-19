"""Who in a team holds an action: the roles that grant it and the people those roles reach there, so a page
that shows "View only" can say which role would let the reader change it and whom to ask. One query per answer; the
console never joins a members list with role grids itself."""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa

from ops_access import ANY_TEAM
from ops_service_kit.http import Out
from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.rows import rows

from .tables import members, role_assignments, role_permissions, roles, teams, users
from .tenancy import TenantDb


class GrantingRole(Out):
    id: str
    name: str


class RoleHolder(Out):
    id: str
    name: str
    email: str
    # The granting roles this person holds in the team.
    roles: list[str]
    # Granted in this team itself, not only by a grant in every team.
    in_team: bool


class Holders(Out):
    # Every role that grants the action, built-in first; the people they reach, those granted in the team first.
    roles: list[GrantingRole]
    holders: list[RoleHolder]


class _Held(Out):
    id: str
    name: str
    email: str
    role_id: str
    here: bool


class HolderStore(TenantDb):
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.RLS})

    async def holders(self, tenant_id: str, team_id: str, area: str, action: str) -> Holders:
        """The roles granting `area.action` and the active people they reach in `team_id`: assigned there or in every
        team (`*`), directly or through a team they are an active member of. Expired assignments reach nobody."""
        now = now_iso()
        granting = (
            sa.select(roles.c.id, roles.c.name)
            .join(role_permissions, role_permissions.c.role_id == roles.c.id)
            .where(role_permissions.c.area == area, role_permissions.c.action == action)
            .order_by(roles.c.builtin.desc(), roles.c.name)
        )
        live = sa.and_(
            role_assignments.c.team_id.in_([team_id, ANY_TEAM]),
            sa.or_(role_assignments.c.expires_at.is_(None), role_assignments.c.expires_at > now),
        )
        # Granted in this team itself, not only through a grant in every team (a workspace admin's, or the install's
        # first admin's): the people a notice names first, as the ones who work in the team.
        # A CASE, not the comparison itself: SQL Server has no boolean value to select.
        here = sa.case((role_assignments.c.team_id == team_id, sa.true()), else_=sa.false()).label("here")
        direct = sa.select(role_assignments.c.subject_id.label("user_id"), role_assignments.c.role_id, here).where(
            live, role_assignments.c.subject_kind == "person"
        )
        via_team = (
            sa.select(members.c.user_id, role_assignments.c.role_id, here)
            .join(members, members.c.team_id == role_assignments.c.subject_id)
            .join(teams, teams.c.id == members.c.team_id)
            .where(
                live,
                role_assignments.c.subject_kind == "team",
                members.c.status == "active",
                teams.c.status == "active",
            )
        )
        held = sa.union(direct, via_team).subquery()
        async with self.tenant_tx(tenant_id) as c:
            found = await rows(c, granting, GrantingRole)
            reached = await rows(
                c,
                sa.select(users.c.id, users.c.name, users.c.email, held.c.role_id, held.c.here)
                .join(held, held.c.user_id == users.c.id)
                .where(held.c.role_id.in_([r.id for r in found]), users.c.status == "active")
                .order_by(users.c.name, users.c.id),
                _Held,
            )
        # One entry per person, in the query's name order, with each granting role they hold once.
        first: dict[str, _Held] = {}
        roles_of: dict[str, list[str]] = {}
        in_team: dict[str, bool] = {}
        for r in reached:
            first.setdefault(r.id, r)
            held_roles = roles_of.setdefault(r.id, [])
            if r.role_id not in held_roles:
                held_roles.append(r.role_id)
            in_team[r.id] = in_team.get(r.id, False) or r.here
        people = [
            RoleHolder(id=p.id, name=p.name, email=p.email, roles=roles_of[p.id], in_team=in_team[p.id])
            for p in first.values()
        ]
        # Those granted in the team first, each part by name.
        return Holders(roles=found, holders=sorted(people, key=lambda h: not h.in_team))
