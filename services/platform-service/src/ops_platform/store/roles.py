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
    Access,
    Assignment,
    Grant,
    Grids,
    active,
    builtin_roles_for,
)
from ops_access.catalogue import ADMIN
from ops_identity import Principal
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.dialect import lock_key

from .audit import record
from .tables import members, role_assignments, role_permissions, roles, teams, tenants, users
from .tenancy import TenantDb

MEMBERSHIP = "membership"


class RoleNameTakenError(Exception):
    """Another role of the workspace has that name."""


class AlreadyGrantedError(Exception):
    """The person holds that role in that team already."""


class RoleInUseError(Exception):
    """People or teams hold the role; `holders` names them."""

    def __init__(self, holders: list[dict[str, Any]]) -> None:
        super().__init__("role in use")
        self.holders = holders


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
        async with self.db.tenant_tx(tenant_id) as c:
            return await holdings_in(c, user_id)

    async def live(
        self, tenant_id: str, user_id: str, *, team: str | None = None, conn: AsyncConnection | None = None
    ) -> tuple[Principal, Access]:
        """The person as `can` sees them now, built from the database with no token: a decision taken before a token
        exists (which teams a sign-in may act in, whether a first SSO sign-in may link) or one that must not trust the
        token's roles (a demoted admin). `conn` reads on the caller's own transaction."""
        if conn is not None:
            return await live_in(conn, tenant_id, user_id, team=team)
        async with self.db.tenant_tx(tenant_id) as c:
            return await live_in(c, tenant_id, user_id, team=team)

    async def workspace_admin(self, tenant_id: str, user_id: str, *, now: str) -> bool:
        """Whether the person holds `access.manage` through a role assigned in every team (`*`): a workspace admin,
        who acts in any team of the workspace whether or not they belong to it."""
        del now  # `live` reads the clock itself
        p, access = await self.live(tenant_id, user_id)
        # `from_any_team`: the token-less caller acts in no team, and `roles_in(p, "*")` reads only `*` assignments.
        return access.may(p, "access", "manage", team=ANY_TEAM, from_any_team=True)

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
        """An access check an admin ran: who checked whom for what, and the answer, in the audit log."""
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

    async def set_grid(
        self, tenant_id: str, role_id: str, grants: list[Grant], *, by: str, request_id: str, action: str
    ) -> bool:
        """Replaces the role's cells with `grants`, audited as `action` (`role.edit`, `role.reset`) with what changed,
        and raises the permission version so every token issued after carries the new grid. False for no such role."""
        async with self.db.tenant_tx(tenant_id) as c:
            if (await c.execute(sa.select(roles.c.id).where(roles.c.id == role_id))).first() is None:
                return False
            before = {(a, x): s for a, x, s in (await _grids(c, [role_id])).get(role_id, [])}
            after = {(a, x): s for a, x, s in grants}
            await c.execute(role_permissions.delete().where(role_permissions.c.role_id == role_id))
            if grants:
                await c.execute(
                    role_permissions.insert(),
                    [
                        {"tenant_id": tenant_id, "role_id": role_id, "area": a, "action": x, "scope": s}
                        for (a, x), s in after.items()
                    ],
                )
            await bump_version(c, tenant_id)
            changed = sorted(
                f"{a}.{x}" for a, x in before.keys() | after.keys() if before.get((a, x)) != after.get((a, x))
            )
            await record(
                c,
                tenant_id=tenant_id,
                team_id=None,
                actor=by,
                action=action,
                target_kind="role",
                target_id=role_id,
                request_id=request_id,
                detail={
                    "changed": changed,
                    "before": {k: before.get(tuple(k.split(".", 1))) for k in changed},  # type: ignore[arg-type]
                    "after": {k: after.get(tuple(k.split(".", 1))) for k in changed},  # type: ignore[arg-type]
                },
            )
        return True

    async def grids(self, tenant_id: str, role_ids: list[str]) -> dict[str, list[Grant]]:
        async with self.db.tenant_tx(tenant_id) as c:
            return await _grids(c, role_ids)

    async def create(
        self, tenant_id: str, *, name: str, description: str, grants: list[Grant], by: str, request_id: str
    ) -> str:
        """A custom role with `grants`, audited as `role.create`; RoleNameTakenError when the name is used."""
        role_id = new_id("role")
        async with self.db.tenant_tx(tenant_id) as c:
            await _name_free(c, tenant_id, name, None)
            await c.execute(
                roles.insert().values(
                    tenant_id=tenant_id,
                    id=role_id,
                    name=name,
                    builtin=False,
                    description=description,
                    created_at=now_iso(),
                )
            )
            if grants:
                await c.execute(
                    role_permissions.insert(),
                    [
                        {"tenant_id": tenant_id, "role_id": role_id, "area": a, "action": x, "scope": sc}
                        for a, x, sc in grants
                    ],
                )
            await record(
                c,
                tenant_id=tenant_id,
                team_id=None,
                actor=by,
                action="role.create",
                target_kind="role",
                target_id=role_id,
                request_id=request_id,
                detail={"name": name, "cells": len(grants)},
            )
        return role_id

    async def rename(
        self, tenant_id: str, role_id: str, *, name: str, description: str | None, by: str, request_id: str
    ) -> None:
        """A custom role's name and description, audited as `role.rename`; RoleNameTakenError when the name is used."""
        async with self.db.tenant_tx(tenant_id) as c:
            before = (
                await c.execute(sa.select(roles.c.name, roles.c.description).where(roles.c.id == role_id))
            ).first()
            await _name_free(c, tenant_id, name, role_id)
            values: dict[str, Any] = {"name": name} | ({"description": description} if description is not None else {})
            await c.execute(roles.update().where(roles.c.id == role_id).values(**values))
            await record(
                c,
                tenant_id=tenant_id,
                team_id=None,
                actor=by,
                action="role.rename",
                target_kind="role",
                target_id=role_id,
                request_id=request_id,
                detail={"from": before.name if before else None, "to": name},
            )

    async def holders(self, tenant_id: str, role_id: str) -> list[dict[str, Any]]:
        """Who holds the role and in which team, each person by name and address."""
        async with self.db.tenant_tx(tenant_id) as c:
            return await self._holders_in(c, role_id)

    async def delete(self, tenant_id: str, role_id: str, *, move_to: str | None, by: str, request_id: str) -> int:
        """Deletes a custom role. While people or teams hold it, RoleInUseError names them, unless `move_to` names the
        role their assignments move to (one that a holder already has in that team is kept once). Audited as
        `role.delete`; returns how many assignments moved."""
        async with self.db.tenant_tx(tenant_id) as c:
            held = (
                await c.execute(
                    sa.select(role_assignments.c.id, role_assignments.c.subject_kind, role_assignments.c.subject_id,
                              role_assignments.c.team_id).where(role_assignments.c.role_id == role_id)
                )
            ).all()  # fmt: skip
            if held and move_to is None:
                raise RoleInUseError(await self._holders_in(c, role_id))
            moved = 0
            for row_id, kind, subject, team in held:
                taken = (
                    await c.execute(
                        sa.select(role_assignments.c.id).where(
                            role_assignments.c.subject_kind == kind,
                            role_assignments.c.subject_id == subject,
                            role_assignments.c.team_id == team,
                            role_assignments.c.role_id == move_to,
                        )
                    )
                ).first()
                if taken is not None:
                    await c.execute(role_assignments.delete().where(role_assignments.c.id == row_id))
                else:
                    await c.execute(
                        role_assignments.update().where(role_assignments.c.id == row_id).values(role_id=move_to)
                    )
                moved += 1
            await c.execute(role_permissions.delete().where(role_permissions.c.role_id == role_id))
            await c.execute(roles.delete().where(roles.c.id == role_id))
            await bump_version(c, tenant_id)
            await record(
                c,
                tenant_id=tenant_id,
                team_id=None,
                actor=by,
                action="role.delete",
                target_kind="role",
                target_id=role_id,
                request_id=request_id,
                detail={"movedTo": move_to, "moved": moved},
            )
        return moved

    async def grants_of(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        """The roles given to the person on their own (not their team role), each with its team and who gave it."""
        q = (
            sa.select(
                role_assignments.c.id,
                role_assignments.c.role_id,
                roles.c.name,
                role_assignments.c.team_id,
                role_assignments.c.expires_at,
                role_assignments.c.granted_by,
                role_assignments.c.created_at,
            )
            .join(roles, roles.c.id == role_assignments.c.role_id)
            .where(
                role_assignments.c.subject_kind == "person",
                role_assignments.c.subject_id == user_id,
                role_assignments.c.source == "grant",
                roles.c.builtin.is_(False),
            )
            .order_by(roles.c.name, role_assignments.c.team_id)
        )
        async with self.db.tenant_tx(tenant_id) as c:
            rows = (await c.execute(q)).all()
        return [
            {
                "id": r[0],
                "roleId": r[1],
                "roleName": r[2],
                "teamId": r[3],
                "expiresAt": r[4],
                "grantedBy": r[5],
                "createdAt": r[6],
            }
            for r in rows
        ]

    async def grant(self, tenant_id: str, user_id: str, role_id: str, team_id: str, *, by: str, request_id: str) -> str:
        """Gives the person a role in a team, audited as `role.grant`; AlreadyGrantedError when they hold it there."""
        grant_id = new_id("ras")
        async with self.db.tenant_tx(tenant_id) as c:
            held = await c.execute(
                sa.select(role_assignments.c.id).where(
                    role_assignments.c.subject_kind == "person",
                    role_assignments.c.subject_id == user_id,
                    role_assignments.c.role_id == role_id,
                    role_assignments.c.team_id == team_id,
                )
            )
            if held.first() is not None:
                raise AlreadyGrantedError
            await c.execute(
                role_assignments.insert().values(
                    id=grant_id,
                    tenant_id=tenant_id,
                    subject_kind="person",
                    subject_id=user_id,
                    role_id=role_id,
                    team_id=team_id,
                    granted_by=by,
                    reason="Given on Access",
                    source="grant",
                    created_at=now_iso(),
                )
            )
            await bump_version(c, tenant_id)
            await record(
                c,
                tenant_id=tenant_id,
                team_id=team_id,
                actor=by,
                action="role.grant",
                target_kind="person",
                target_id=user_id,
                request_id=request_id,
                detail={"roleId": role_id, "teamId": team_id},
            )
        return grant_id

    async def grant_row(self, tenant_id: str, grant_id: str) -> dict[str, Any] | None:
        async with self.db.tenant_tx(tenant_id) as c:
            row = (
                await c.execute(
                    sa.select(
                        role_assignments.c.subject_id, role_assignments.c.role_id, role_assignments.c.team_id
                    ).where(role_assignments.c.id == grant_id, role_assignments.c.source == "grant")
                )
            ).first()
        return {"subjectId": row[0], "roleId": row[1], "teamId": row[2]} if row else None

    async def ungrant(self, tenant_id: str, grant_id: str, *, by: str, request_id: str) -> bool:
        """Takes a given role away, audited as `role.ungrant`; False when no such grant."""
        async with self.db.tenant_tx(tenant_id) as c:
            row = (
                await c.execute(
                    role_assignments.delete()
                    .where(role_assignments.c.id == grant_id, role_assignments.c.source == "grant")
                    .returning(role_assignments.c.subject_id, role_assignments.c.role_id, role_assignments.c.team_id)
                )
            ).first()
            if row is None:
                return False
            await bump_version(c, tenant_id)
            await record(
                c,
                tenant_id=tenant_id,
                team_id=str(row[2]),
                actor=by,
                action="role.ungrant",
                target_kind="person",
                target_id=str(row[0]),
                request_id=request_id,
                detail={"roleId": row[1], "teamId": row[2]},
            )
        return True

    async def _holders_in(self, c: AsyncConnection, role_id: str) -> list[dict[str, Any]]:
        q = (
            sa.select(role_assignments.c.subject_kind, role_assignments.c.subject_id, role_assignments.c.team_id,
                      users.c.name, users.c.email)
            .outerjoin(users, sa.and_(users.c.id == role_assignments.c.subject_id,
                                      role_assignments.c.subject_kind == "person"))
            .where(role_assignments.c.role_id == role_id)
            .order_by(users.c.name, role_assignments.c.team_id)
        )  # fmt: skip
        return [
            {"kind": r[0], "id": r[1], "teamId": r[2], "name": r[3] or r[1], "email": r[4]}
            for r in (await c.execute(q)).all()
        ]

    async def version(self, tenant_id: str) -> int:
        async with self.db.tenant_tx(tenant_id) as c:
            return await version_in(c, tenant_id)

    async def security_team(self, tenant_id: str) -> str | None:
        """The workspace's Security team, from its record; None when it names none."""
        async with self.db.tenant_tx(tenant_id) as c:
            return (await c.execute(sa.select(tenants.c.security_team_id).where(tenants.c.id == tenant_id))).scalar()


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


async def _name_free(c: AsyncConnection, tenant_id: str, name: str, role_id: str | None) -> None:
    """No two roles of a workspace share a name, case aside: a role is chosen by name on every role picker. The lock
    makes two creates of one name wait for each other, so the second sees the first."""
    await lock_key(c, f"roles:{tenant_id}")
    q = sa.select(roles.c.id).where(sa.func.lower(roles.c.name) == name.lower())
    if role_id is not None:
        q = q.where(roles.c.id != role_id)
    if (await c.execute(q)).first() is not None:
        raise RoleNameTakenError


async def live_in(
    c: AsyncConnection, tenant_id: str, user_id: str, *, team: str | None = None
) -> tuple[Principal, Access]:
    """`RoleStore.live` on the caller's transaction."""
    held = await holdings_in(c, user_id)
    live = active(held.assignments, now_iso())
    version = await version_in(c, tenant_id)
    p = Principal(
        kind="person",
        sub=user_id,
        email="",
        name="",
        roles={},
        scopes=[],
        tenant_id=tenant_id,
        team_id=team,
        team_ids=list(held.teams),
        access={t: [a.role_id for a in live if a.team_id == t] for t in {a.team_id for a in live}},
        permission_version=version,
        auth_method="session",
    )
    security = (await c.execute(sa.select(tenants.c.security_team_id).where(tenants.c.id == tenant_id))).scalar()
    access = Access(security_team=security, grids=Grids(fetch=lambda _t, _v, ids: _grids(c, ids)))
    # The built-in roles too, so a refusal names who holds the cell in this workspace.
    await access.grids.load(tenant_id, version, [*{a.role_id for a in live}, *(r.id for r in BUILTIN_ROLES)])
    # Loaded once on `c`; a later load would read on a transaction that has ended.
    access.grids.fetch = None
    return p, access


async def holdings_in(c: AsyncConnection, user_id: str) -> Holdings:
    """`RoleStore.holdings` on the caller's transaction."""
    mine = (
        sa.select(teams.c.id, teams.c.name)
        .join(members, members.c.team_id == teams.c.id)
        .where(members.c.user_id == user_id, members.c.status == "active", teams.c.status == "active")
    )
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
    # An assignment in an archived team grants nothing there.
    archived = {str(t) for t in (await c.execute(sa.select(teams.c.id).where(teams.c.status != "active"))).scalars()}
    rows = [r for r in rows if str(r[2]) not in archived]
    # A team named by an assignment but not a membership still needs its name.
    extra = {str(r[2]) for r in rows} - set(names) - {"*"}
    if extra:
        more = await c.execute(sa.select(teams.c.id, teams.c.name).where(teams.c.id.in_(sorted(extra))))
        names |= {str(r[0]): str(r[1]) for r in more.all()}
    assignments = [Assignment(str(r[0]), str(r[1]), str(r[2]), r[3], r[4]) for r in rows]
    return Holdings(teams=names, assignments=assignments)


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
    """The workspace's owner: while it has none, its earliest account admin (Admin in every team) becomes it,
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
    security_team: str | None,
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
