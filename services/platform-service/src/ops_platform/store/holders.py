"""Who in a team holds an action (c-186): the roles that grant it and the people those roles reach there, so a page
that shows "View only" can say which role would let the reader change it and whom to ask. One query per answer; the
console never joins a members list with role grids itself."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa

from ops_access import ANY_TEAM
from ops_service_kit.ids import now_iso
from ops_store import Guarantee

from .tables import members, role_assignments, role_permissions, roles, teams, users
from .tenancy import TenantDb


class HolderStore:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.RLS})

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def holders(self, tenant_id: str, team_id: str, area: str, action: str) -> dict[str, Any]:
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
        direct = sa.select(role_assignments.c.subject_id.label("user_id"), role_assignments.c.role_id).where(
            live, role_assignments.c.subject_kind == "person"
        )
        via_team = (
            sa.select(members.c.user_id, role_assignments.c.role_id)
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
        async with self.db.tenant_tx(tenant_id) as c:
            found = [(str(r[0]), str(r[1])) for r in (await c.execute(granting)).all()]
            ids = [i for i, _ in found]
            rows = (
                await c.execute(
                    sa.select(users.c.id, users.c.name, users.c.email, held.c.role_id)
                    .join(held, held.c.user_id == users.c.id)
                    .where(held.c.role_id.in_(ids), users.c.status == "active")
                    .order_by(users.c.name, users.c.id)
                )
            ).all()
        people: dict[str, dict[str, Any]] = {}
        for uid, name, email, role_id in rows:
            person = people.setdefault(str(uid), {"id": str(uid), "name": str(name), "email": str(email), "roles": []})
            if role_id not in person["roles"]:
                person["roles"].append(str(role_id))
        return {"roles": [{"id": i, "name": n} for i, n in found], "holders": list(people.values())}
