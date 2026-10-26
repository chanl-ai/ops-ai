"""Roles, their permissions and assignments.

Reads run in `tenant_tx`, so row-level security keeps every tenant's roles to itself. The writes here are helpers that
run inside a caller's transaction: a membership change and the assignments that mirror it commit together, so no
reader ever sees a role in `members` that the assignments disagree with. Every such change raises the tenant's
`permission_version` in the same transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_access import (
    ANY_TEAM,
    BUILTIN_IDS,
    BUILTIN_ROLES,
    OWNER,
    Assignment,
    Grant,
    active,
    builtin_roles_for,
    effective,
)
from ops_access.catalogue import ADMIN
from ops_service_kit.ids import new_id
from ops_store import Guarantee

from .audit import record
from .tables import members, role_assignments, role_permissions, roles, teams, tenants
from .tenancy import TenantDb

MEMBERSHIP = "membership"


@dataclass(frozen=True)
class Holdings:
    """A person's member teams (id to name) and every assignment that may apply to them, expired ones included."""

    teams: dict[str, str]
    assignments: list[Assignment]


class RoleStore:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def roles(self, tenant_id: str) -> list[dict[str, Any]]:
        """Every role with its permission and assignment counts, built-in roles first in their fixed order."""
        perms = (
            sa.select(role_permissions.c.role_id, sa.func.count().label("n"))
            .group_by(role_permissions.c.role_id)
            .subquery()
        )
        held = (
            sa.select(role_assignments.c.role_id, sa.func.count().label("n"))
            .group_by(role_assignments.c.role_id)
            .subquery()
        )
        q = (
            sa.select(
                roles.c.id,
                roles.c.name,
                roles.c.builtin,
                roles.c.description,
                sa.func.coalesce(perms.c.n, 0),
                sa.func.coalesce(held.c.n, 0),
            )
            .outerjoin(perms, perms.c.role_id == roles.c.id)
            .outerjoin(held, held.c.role_id == roles.c.id)
            .order_by(roles.c.builtin.desc(), sa.func.lower(roles.c.name), roles.c.id)
        )
        async with self.db.tenant_tx(tenant_id) as c:
            rows = (await c.execute(q)).all()
        order = {r.id: i for i, r in enumerate(BUILTIN_ROLES)}
        out = [
            {
                "id": r[0],
                "name": r[1],
                "builtin": bool(r[2]),
                "description": r[3],
                "permissionCount": int(r[4]),
                "assignmentCount": int(r[5]),
            }
            for r in rows
        ]
        return sorted(out, key=lambda r: (not r["builtin"], order.get(r["id"], 0)))

    async def role(self, tenant_id: str, role_id: str) -> dict[str, Any] | None:
        async with self.db.tenant_tx(tenant_id) as c:
            row = (await c.execute(sa.select(roles).where(roles.c.id == role_id))).mappings().first()
            if row is None:
                return None
            held = await c.execute(
                sa.select(sa.func.count()).select_from(role_assignments).where(role_assignments.c.role_id == role_id)
            )
            grants = await _grids(c, [role_id])
        return {
            "id": row["id"],
            "name": row["name"],
            "builtin": bool(row["builtin"]),
            "description": row["description"],
            "assignmentCount": int(held.scalar_one()),
            "grants": grants.get(role_id, []),
        }

    async def holdings(self, tenant_id: str, user_id: str) -> Holdings:
        """The person's active teams and the assignments made to them or to one of those teams."""
        mine = (
            sa.select(teams.c.id, teams.c.name)
            .join(members, members.c.team_id == teams.c.id)
            .where(members.c.user_id == user_id, members.c.status == "active", teams.c.status == "active")
        )
        async with self.db.tenant_tx(tenant_id) as c:
            names = {str(r[0]): str(r[1]) for r in (await c.execute(mine)).all()}
            subject = sa.or_(
                sa.and_(role_assignments.c.subject_kind == "person", role_assignments.c.subject_id == user_id),
                sa.and_(role_assignments.c.subject_kind == "team", role_assignments.c.subject_id.in_(list(names))),
            )
            q = (
                sa.select(
                    role_assignments.c.role_id,
                    roles.c.name,
                    role_assignments.c.team_id,
                    role_assignments.c.subject_kind,
                    role_assignments.c.expires_at,
                )
                .join(roles, roles.c.id == role_assignments.c.role_id)
                .where(subject)
                .order_by(role_assignments.c.created_at, role_assignments.c.id)
            )
            rows = (await c.execute(q)).all()
            # An assignment in an archived team grants nothing there (c-198).
            archived = {
                str(t) for t in (await c.execute(sa.select(teams.c.id).where(teams.c.status != "active"))).scalars()
            }
            rows = [r for r in rows if str(r[2]) not in archived]
            # A team named by an assignment but not a membership still needs its name.
            extra = {str(r[2]) for r in rows} - set(names) - {"*"}
            if extra:
                more = await c.execute(sa.select(teams.c.id, teams.c.name).where(teams.c.id.in_(sorted(extra))))
                names |= {str(r[0]): str(r[1]) for r in more.all()}
        assignments = [Assignment(str(r[0]), str(r[1]), str(r[2]), r[3], r[4]) for r in rows]
        return Holdings(teams=names, assignments=assignments)

    async def workspace_admin(self, tenant_id: str, user_id: str, *, now: str) -> bool:
        """Whether the person holds `access.manage` through a role assigned in every team (`*`): a workspace admin,
        who acts in any team of the workspace whether or not they belong to it (owner, 2026-10-17; c-208)."""
        held = await self.holdings(tenant_id, user_id)
        every = [a for a in active(held.assignments, now) if a.team_id == ANY_TEAM]
        if not every:
            return False
        grids = await self.grids(tenant_id, sorted({a.role_id for a in every}))
        return ("access", "manage") in effective(every, grids, [ANY_TEAM], now).get(ANY_TEAM, {})

    async def workspace_roles(self, tenant_id: str, user_ids: list[str], *, now: str) -> dict[str, list[str]]:
        """Each person's roles assigned in every team (`*`), by name, so a team's member list says where access beyond
        their team role comes from (a Viewer of the team who is also a workspace Admin)."""
        if not user_ids:
            return {}
        q = (
            sa.select(role_assignments.c.subject_id, roles.c.name)
            .join(roles, roles.c.id == role_assignments.c.role_id)
            .where(
                role_assignments.c.subject_kind == "person",
                role_assignments.c.subject_id.in_(user_ids),
                role_assignments.c.team_id == ANY_TEAM,
                sa.or_(role_assignments.c.expires_at.is_(None), role_assignments.c.expires_at > now),
            )
            .order_by(roles.c.name)
        )
        out: dict[str, list[str]] = {}
        async with self.db.tenant_tx(tenant_id) as c:
            for subject, name in (await c.execute(q)).all():
                out.setdefault(str(subject), []).append(str(name))
        return out

    async def record_check(
        self, tenant_id: str, team_id: str, *, by: str, request_id: str, detail: dict[str, Any]
    ) -> None:
        """An access check an admin ran (c-150): who checked whom for what, and the answer, in the audit log."""
        async with self.db.tenant_tx(tenant_id) as c:
            await record(
                c,
                tenant_id=tenant_id,
                team_id=team_id,
                actor=by,
                action="access.check",
                target_kind="person",
                target_id=str(detail.get("personId") or ""),
                request_id=request_id,
                detail=detail,
            )

    async def active_teams(self, tenant_id: str) -> dict[str, str]:
        """Every active team of the workspace, id to name, oldest first."""
        q = (
            sa.select(teams.c.id, teams.c.name)
            .where(teams.c.status == "active")
            .order_by(teams.c.created_at, teams.c.id)
        )
        async with self.db.tenant_tx(tenant_id) as c:
            return {str(r[0]): str(r[1]) for r in (await c.execute(q)).all()}

    async def grids(self, tenant_id: str, role_ids: list[str]) -> dict[str, list[Grant]]:
        async with self.db.tenant_tx(tenant_id) as c:
            return await _grids(c, role_ids)

    async def version(self, tenant_id: str) -> int:
        async with self.db.tenant_tx(tenant_id) as c:
            return await version_in(c, tenant_id)


async def _grids(c: AsyncConnection, role_ids: list[str]) -> dict[str, list[Grant]]:
    q = (
        sa.select(
            role_permissions.c.role_id, role_permissions.c.area, role_permissions.c.action, role_permissions.c.scope
        )
        .where(role_permissions.c.role_id.in_(role_ids))
        .order_by(role_permissions.c.role_id, role_permissions.c.area, role_permissions.c.action)
    )
    out: dict[str, list[Grant]] = {}
    for role_id, area, action, scope in (await c.execute(q)).all():
        out.setdefault(str(role_id), []).append((str(area), str(action), "own" if scope == "own" else "all"))
    return out


async def version_in(c: AsyncConnection, tenant_id: str) -> int:
    found = (await c.execute(sa.select(tenants.c.permission_version).where(tenants.c.id == tenant_id))).scalar()
    return int(found or 0)


async def bump_version(c: AsyncConnection, tenant_id: str) -> None:
    await c.execute(
        tenants.update().where(tenants.c.id == tenant_id).values(permission_version=tenants.c.permission_version + 1)
    )


async def ensure_builtin_roles(c: AsyncConnection, tenant_id: str, *, at: str) -> None:
    """The five built-in roles and their grid for a tenant made after migration 0006 (the dev seed, tests). Rows that
    exist are left as they are; a missing one is added."""
    q = sa.select(roles.c.id).where(roles.c.tenant_id == tenant_id, roles.c.id.in_(sorted(BUILTIN_IDS)))
    have = {str(r) for r in (await c.execute(q)).scalars()}
    for role in BUILTIN_ROLES:
        if role.id in have:
            continue
        await c.execute(
            roles.insert().values(
                tenant_id=tenant_id,
                id=role.id,
                name=role.name,
                builtin=True,
                description=role.description,
                created_at=at,
            )
        )
        await c.execute(
            role_permissions.insert(),
            [
                {"tenant_id": tenant_id, "role_id": role.id, "area": a, "action": x, "scope": s}
                for a, x, s in role.grants
            ],
        )


async def ensure_owner(c: AsyncConnection, tenant_id: str, *, at: str) -> str | None:
    """The workspace's owner (c-529): while it has none, its earliest account admin (Admin in every team) becomes it,
    as migration 0026 did for workspaces made before it. None when it has no account admin."""
    owner = role_assignments.c.role_id == OWNER.id
    found = (
        await c.execute(
            sa.select(role_assignments.c.subject_id).where(role_assignments.c.tenant_id == tenant_id, owner)
        )
    ).scalar()
    if found is not None:
        return str(found)
    first = (
        await c.execute(
            sa.select(role_assignments.c.subject_id)
            .where(
                role_assignments.c.tenant_id == tenant_id,
                role_assignments.c.role_id == ADMIN.id,
                role_assignments.c.team_id == ANY_TEAM,
                role_assignments.c.subject_kind == "person",
            )
            .order_by(role_assignments.c.created_at, role_assignments.c.id)
            .limit(1)
        )
    ).scalar()
    if first is None:
        return None
    await c.execute(
        role_assignments.insert().values(
            id=new_id("ras"), tenant_id=tenant_id, subject_kind="person", subject_id=first, role_id=OWNER.id,
            team_id=ANY_TEAM, granted_by="seed", reason="The workspace's first account admin", source="grant",
            created_at=at,
        )
    )  # fmt: skip
    await bump_version(c, tenant_id)
    return str(first)


async def mirror_membership(
    c: AsyncConnection,
    *,
    tenant_id: str,
    team_id: str,
    user_id: str,
    member_role: str | None,
    security_team: str,
    granted_by: str,
    at: str,
) -> None:
    """Makes the person's membership assignments in `team_id` equal `member_role` (None: removed), leaving grants
    made on their own alone, and raises the tenant's version when anything changed."""
    want: set[str] = (
        set(builtin_roles_for(member_role, security_team=team_id == security_team)) if member_role else set()
    )
    mine = sa.and_(
        role_assignments.c.tenant_id == tenant_id,
        role_assignments.c.subject_kind == "person",
        role_assignments.c.subject_id == user_id,
        role_assignments.c.team_id == team_id,
        role_assignments.c.source == MEMBERSHIP,
    )
    have = {str(r) for r in (await c.execute(sa.select(role_assignments.c.role_id).where(mine))).scalars()}
    if have == want:
        return
    if have - want:
        await c.execute(role_assignments.delete().where(mine, role_assignments.c.role_id.in_(sorted(have - want))))
    for role_id in sorted(want - have):
        await c.execute(
            role_assignments.insert().values(
                id=new_id("ras"),
                tenant_id=tenant_id,
                subject_kind="person",
                subject_id=user_id,
                role_id=role_id,
                team_id=team_id,
                granted_by=granted_by,
                reason=f"Team membership as {member_role}",
                source=MEMBERSHIP,
                created_at=at,
            )
        )
    await bump_version(c, tenant_id)
