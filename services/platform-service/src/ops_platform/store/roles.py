"""Roles, their permissions and assignments.

Reads run in `tenant_tx`, so row-level security keeps every tenant's roles to itself. The writes here are helpers that
run inside a caller's transaction: a membership change and the assignments that mirror it commit together, so no
reader ever sees a role in `members` that the assignments disagree with. Every such change raises the tenant's
`permission_version` in the same transaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

import sqlalchemy as sa
from pydantic import JsonValue
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
    effective_grids,
    privileged_cells,
)
from ops_access.catalogue import ADMIN
from ops_access.check import FetchGrids
from ops_identity import Principal
from ops_service_kit.http import Out
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.listing import ListParams
from ops_store import Guarantee
from ops_store.dialect import lock_key
from ops_store.listing import ListPage, list_page
from ops_store.rows import one, rows

from .audit import record
from .tables import (
    group_members,
    groups,
    members,
    role_assignments,
    role_permissions,
    roles,
    signin_break_glass,
    teams,
    tenants,
    users,
)
from .tenancy import TenantDb

MEMBERSHIP = "membership"


class RoleNameTakenError(Exception):
    """Another role of the workspace has that name."""


class AlreadyGrantedError(Exception):
    """The person holds that role in that team already."""


class UnknownGroupError(Exception):
    """No group of the workspace has that id."""


class PrivilegedForGroupError(Exception):
    """The role holds cells a group's assignment never carries (`ops_access.PRIVILEGED`); `cells` names them."""

    def __init__(self, cells: list[str]) -> None:
        super().__init__("privileged role for a group")
        self.cells = cells


class RoleSummary(Out):
    id: str
    name: str
    builtin: bool
    description: str
    permission_count: int
    assignment_count: int


class _RoleHead(Out):
    id: str
    name: str
    builtin: bool
    description: str
    assignment_count: int


class RoleRow(Out):
    """A role with its cells and how many assignments hold it."""

    id: str
    name: str
    builtin: bool
    description: str
    assignment_count: int
    grants: list[Grant]


class RoleHolderRow(Out):
    kind: Literal["person", "team", "group"]
    id: str
    team_id: str
    # The person's name, or the id when the holder is a team or a person with no name.
    name: str
    email: str | None


class RoleGrantRow(Out):
    """A role given to a person on their own, with its team and who gave it."""

    id: str
    role_id: str
    role_name: str
    team_id: str
    expires_at: str | None
    granted_by: str
    created_at: str


class GrantRef(Out):
    subject_id: str
    role_id: str
    team_id: str


class _Held(Out):
    subject_kind: Literal["person", "team", "group"]
    subject_id: str
    team_id: str
    name: str | None
    email: str | None


class RoleInUseError(Exception):
    """People or teams hold the role; `holders` names them."""

    def __init__(self, holders: list[RoleHolderRow]) -> None:
        super().__init__("role in use")
        self.holders = holders


@dataclass(frozen=True)
class Holdings:
    """A person's member teams (id to name) and every assignment that may apply to them, expired ones included."""

    teams: dict[str, str]
    assignments: list[Assignment]


class RoleStore(TenantDb):
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    async def roles(self, tenant_id: str, params: ListParams) -> ListPage:
        """The roles on the shared list contract, with their permission and assignment counts: built-in roles first in
        their fixed order, then custom roles by name, then by id; searched on name; `builtin` and `canDecideReviews`
        ("true" or "false") keep built-in or custom roles and roles that do or do not grant reviews.decide."""
        held = (
            sa.select(role_assignments.c.role_id, sa.func.count().label("n"))
            .group_by(role_assignments.c.role_id)
            .subquery()
        )
        # One sort key: a built-in role's place in BUILTIN_ROLES ("0" and two digits), else "1" and the lower-case name.
        place = sa.case(
            {b.id: f"0{n:02d}" for n, b in enumerate(BUILTIN_ROLES)},
            value=roles.c.id,
            else_=sa.literal("1") + sa.func.lower(roles.c.name),
        )
        async with self.tenant_tx(tenant_id) as c:
            # The cells come from grids_in, as the live check reads them, never counted off the table: a built-in
            # role with no rows holds its seed.
            _, grids = await named_grids(c)
            deciding = sorted(r for r, g in grids.items() if any((a, x) == ("reviews", "decide") for a, x, _ in g))
            decides = roles.c.id.in_(deciding) if deciding else sa.false()
            # The filters compare query text, so each is the "true" or "false" its condition reads as.
            flags = {
                "builtin": sa.case((roles.c.builtin == sa.true(), "true"), else_="false"),
                "canDecideReviews": sa.case((decides, "true"), else_="false"),
            }
            assigned = sa.func.coalesce(held.c.n, 0)
            q = sa.select(
                roles.c.id,
                roles.c.name,
                roles.c.builtin,
                roles.c.description,
                assigned.label("assignment_count"),
            ).select_from(roles.outerjoin(held, held.c.role_id == roles.c.id))
            page = await list_page(
                c,
                q,
                params,
                search=[roles.c.name],
                sortable={"name": roles.c.name, "assignmentCount": assigned},
                default_sort=place.asc(),
                filters=flags,
            )
        page["data"] = [
            RoleSummary.model_validate({**r, "permission_count": len(grids.get(str(r["id"]), []))}).model_dump(
                by_alias=True
            )
            for r in page["data"]
        ]
        return page

    async def role_by_id(self, tenant_id: str, role_id: str) -> RoleRow | None:
        held = (
            sa.select(sa.func.count())
            .select_from(role_assignments)
            .where(role_assignments.c.role_id == role_id)
            .scalar_subquery()
        )
        q = sa.select(
            roles.c.id, roles.c.name, roles.c.builtin, roles.c.description, held.label("assignment_count")
        ).where(roles.c.id == role_id)
        async with self.tenant_tx(tenant_id) as c:
            head = await one(c, q, _RoleHead)
            if head is None:
                return None
            grants = await grids_in(c, [role_id])
        return RoleRow(**head.model_dump(), grants=grants.get(role_id, []))

    async def holdings(self, tenant_id: str, user_id: str) -> Holdings:
        """The person's active teams and the assignments made to them or to one of those teams."""
        async with self.tenant_tx(tenant_id) as c:
            return await holdings_in(c, user_id)

    async def live(
        self, tenant_id: str, user_id: str, *, team: str | None = None, conn: AsyncConnection | None = None
    ) -> tuple[Principal, Access]:
        """The person as `can` sees them now, built from the database with no token: a decision taken before a token
        exists (which teams a sign-in may act in, whether a first SSO sign-in may link) or one that must not trust the
        token's roles (a demoted admin). `conn` reads on the caller's own transaction."""
        if conn is not None:
            return await live_in(conn, tenant_id, user_id, team=team)
        async with self.tenant_tx(tenant_id) as c:
            return await live_in(c, tenant_id, user_id, team=team)

    async def workspace_admin(self, tenant_id: str, user_id: str, *, now: str) -> bool:
        """Whether the person holds `access.manage` through a role assigned in every team (`*`): a workspace admin,
        who acts in any team of the workspace whether or not they belong to it."""
        del now  # `live` reads the clock itself
        return is_workspace_admin(*await self.live(tenant_id, user_id))

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
        async with self.tenant_tx(tenant_id) as c:
            for subject, name in (await c.execute(q)).all():
                out.setdefault(str(subject), []).append(str(name))
        return out

    async def record_check(
        self, tenant_id: str, team_id: str, *, by: str, request_id: str, detail: Mapping[str, JsonValue]
    ) -> None:
        """An access check an admin ran: who checked whom for what, and the answer, in the audit log."""
        async with self.tenant_tx(tenant_id) as c:
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
        async with self.tenant_tx(tenant_id) as c:
            return {str(r[0]): str(r[1]) for r in (await c.execute(q)).all()}

    async def set_grid(
        self, tenant_id: str, role_id: str, grants: list[Grant], *, by: str, request_id: str, action: str
    ) -> bool:
        """Replaces the role's cells with `grants`, audited as `action` (`role.edit`, `role.reset`) with what changed,
        and raises the permission version so every token issued after carries the new grid. False for no such role."""
        async with self.tenant_tx(tenant_id) as c:
            if (await c.execute(sa.select(roles.c.id).where(roles.c.id == role_id))).first() is None:
                return False
            before = {(a, x): s for a, x, s in (await grids_in(c, [role_id])).get(role_id, [])}
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
        async with self.tenant_tx(tenant_id) as c:
            return await grids_in(c, role_ids)

    async def create(
        self, tenant_id: str, *, name: str, description: str, grants: list[Grant], by: str, request_id: str
    ) -> str:
        """A custom role with `grants`, audited as `role.create`; RoleNameTakenError when the name is used."""
        role_id = new_id("role")
        async with self.tenant_tx(tenant_id) as c:
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
        async with self.tenant_tx(tenant_id) as c:
            before = (
                await c.execute(sa.select(roles.c.name, roles.c.description).where(roles.c.id == role_id))
            ).first()
            await _name_free(c, tenant_id, name, role_id)
            values: dict[str, str] = {"name": name} | ({"description": description} if description is not None else {})
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

    async def holders(self, tenant_id: str, role_id: str, params: ListParams) -> ListPage:
        """Who holds the role and in which team on the shared list contract, each person by name and address: by name
        (a team's id standing in for its name, on both databases alike), then by assignment id; searched on name and
        email; a group holder is named by the group's name. `ids` names the row's `id`, the person's, group's or
        team's, not the assignment's."""
        name = sa.func.coalesce(users.c.name, groups.c.name, role_assignments.c.subject_id)
        q = (
            sa.select(role_assignments.c.subject_kind.label("kind"), role_assignments.c.subject_id.label("id"),
                      role_assignments.c.team_id, name.label("name"), users.c.email)
            .select_from(role_assignments.outerjoin(users, sa.and_(users.c.id == role_assignments.c.subject_id,
                                                                   role_assignments.c.subject_kind == "person"))
                         .outerjoin(groups, sa.and_(groups.c.id == role_assignments.c.subject_id,
                                                    role_assignments.c.subject_kind == "group")))
            .where(role_assignments.c.role_id == role_id)
        )  # fmt: skip
        if params.ids is not None:
            q = q.where(role_assignments.c.subject_id.in_(params.ids))
            params = params.model_copy(update={"ids": None, "search": None})
        async with self.tenant_tx(tenant_id) as c:
            page = await list_page(c, q, params, search=[users.c.name, users.c.email], default_sort=name.asc())
        page["data"] = [RoleHolderRow.model_validate(r).model_dump(by_alias=True) for r in page["data"]]
        return page

    async def holder_options(
        self, tenant_id: str, team_id: str, *, search: str | None, ids: list[str], offset: int, limit: int
    ) -> list[dict[str, str | None]]:
        """Who a role can be given to in the team, as one picker's choices: the team's active people and the
        workspace's groups, by name, searched on name (and a person's email) and paged here. Each value is
        `person:<user id>` or `group:<group id>`; `ids` resolves stored values to their names."""
        person_name = sa.func.coalesce(users.c.name, members.c.email)
        people = (
            sa.select(sa.literal("person").label("kind"), members.c.user_id.label("id"), person_name.label("name"),
                      members.c.email.label("hint"))
            .select_from(members.outerjoin(users, users.c.id == members.c.user_id))
            .where(members.c.team_id == team_id, members.c.status == "active", members.c.user_id.is_not(None))
        )  # fmt: skip
        sets = sa.select(
            sa.literal("group").label("kind"), groups.c.id, groups.c.name, sa.literal("Group").label("hint")
        )
        wanted = [i.split(":", 1) for i in ids if ":" in i]
        if wanted:
            people = people.where(members.c.user_id.in_([v for k, v in wanted if k == "person"] or [""]))
            sets = sets.where(groups.c.id.in_([v for k, v in wanted if k == "group"] or [""]))
        elif search:
            like = f"%{search.strip().lower()}%"
            people = people.where(
                sa.or_(sa.func.lower(person_name).like(like), sa.func.lower(members.c.email).like(like))
            )
            sets = sets.where(sa.func.lower(groups.c.name).like(like))
        both = sa.union_all(people, sets).subquery()
        q = sa.select(both).order_by(both.c.name, both.c.kind, both.c.id).offset(offset).limit(limit)
        async with self.tenant_tx(tenant_id) as c:
            found = (await c.execute(q)).all()
        return [{"id": f"{r.kind}:{r.id}", "label": r.name, "hint": r.hint} for r in found]

    async def delete(self, tenant_id: str, role_id: str, *, move_to: str | None, by: str, request_id: str) -> int:
        """Deletes a custom role. While people or teams hold it, RoleInUseError names them, unless `move_to` names the
        role their assignments move to (one that a holder already has in that team is kept once). Audited as
        `role.delete`; returns how many assignments moved."""
        async with self.tenant_tx(tenant_id) as c:
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

    async def grants_of(self, tenant_id: str, user_id: str, params: ListParams) -> ListPage:
        """The roles given to the person on their own (not their team role), each with its team and who gave it, on
        the shared list contract: by role name, then by assignment id; searched on the role's name."""
        q = (
            sa.select(
                role_assignments.c.id,
                role_assignments.c.role_id,
                roles.c.name.label("role_name"),
                role_assignments.c.team_id,
                role_assignments.c.expires_at,
                role_assignments.c.granted_by,
                role_assignments.c.created_at,
            )
            .select_from(role_assignments.join(roles, roles.c.id == role_assignments.c.role_id))
            .where(
                role_assignments.c.subject_kind == "person",
                role_assignments.c.subject_id == user_id,
                role_assignments.c.source == "grant",
                roles.c.builtin == sa.false(),
            )
        )
        async with self.tenant_tx(tenant_id) as c:
            page = await list_page(c, q, params, search=[roles.c.name], default_sort=roles.c.name.asc())
        page["data"] = [RoleGrantRow.model_validate(r).model_dump(by_alias=True) for r in page["data"]]
        return page

    async def grant(self, tenant_id: str, user_id: str, role_id: str, team_id: str, *, by: str, request_id: str) -> str:
        """Gives the person a role in a team, audited as `role.grant`; AlreadyGrantedError when they hold it there."""
        return await self.assign(
            tenant_id, subject_kind="person", subject_id=user_id, role_id=role_id, team_id=team_id, by=by,
            request_id=request_id,
        )  # fmt: skip

    async def assign(
        self,
        tenant_id: str,
        *,
        subject_kind: Literal["person", "group"],
        subject_id: str,
        role_id: str,
        team_id: str,
        by: str,
        request_id: str,
        expires_at: str | None = None,
    ) -> str:
        """Gives a person or a group a role in one team or in every team (`*`), audited as `role.grant`. A group is
        never given a role holding a privileged cell there (PrivilegedForGroupError naming the cells), nor is a group
        the workspace does not have (UnknownGroupError); AlreadyGrantedError when the subject holds the role there."""
        grant_id = new_id("ras")
        async with self.tenant_tx(tenant_id) as c:
            if subject_kind == "group":
                if (await c.execute(sa.select(groups.c.id).where(groups.c.id == subject_id))).first() is None:
                    raise UnknownGroupError
                await _refuse_privileged_for_group(c, tenant_id, role_id, team_id)
            held = await c.execute(
                sa.select(role_assignments.c.id).where(
                    role_assignments.c.subject_kind == subject_kind,
                    role_assignments.c.subject_id == subject_id,
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
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    role_id=role_id,
                    team_id=team_id,
                    expires_at=expires_at,
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
                team_id=None if team_id == ANY_TEAM else team_id,
                actor=by,
                action="role.grant",
                target_kind=subject_kind,
                target_id=subject_id,
                request_id=request_id,
                detail={"roleId": role_id, "teamId": team_id},
            )
        return grant_id

    async def grant_row(self, tenant_id: str, grant_id: str) -> GrantRef | None:
        q = sa.select(role_assignments.c.subject_id, role_assignments.c.role_id, role_assignments.c.team_id).where(
            role_assignments.c.id == grant_id, role_assignments.c.source == "grant"
        )
        async with self.tenant_tx(tenant_id) as c:
            return await one(c, q, GrantRef)

    async def ungrant(self, tenant_id: str, grant_id: str, *, by: str, request_id: str) -> bool:
        """Takes a given role away from a person or a group, audited as `role.ungrant`; False when no such grant.
        Taking a group's away ends only what that assignment gave: each person keeps what they hold on their own or
        through another group."""
        async with self.tenant_tx(tenant_id) as c:
            row = (
                await c.execute(
                    role_assignments.delete()
                    .where(role_assignments.c.id == grant_id, role_assignments.c.source == "grant")
                    .returning(
                        role_assignments.c.subject_id,
                        role_assignments.c.role_id,
                        role_assignments.c.team_id,
                        role_assignments.c.subject_kind,
                    )
                )
            ).first()
            if row is None:
                return False
            await bump_version(c, tenant_id)
            await record(
                c,
                tenant_id=tenant_id,
                team_id=None if row[2] == ANY_TEAM else str(row[2]),
                actor=by,
                action="role.ungrant",
                target_kind=str(row[3]),
                target_id=str(row[0]),
                request_id=request_id,
                detail={"roleId": row[1], "teamId": row[2]},
            )
        return True

    async def _holders_in(self, c: AsyncConnection, role_id: str) -> list[RoleHolderRow]:
        q = (
            sa.select(role_assignments.c.subject_kind, role_assignments.c.subject_id, role_assignments.c.team_id,
                      users.c.name, users.c.email)
            .outerjoin(users, sa.and_(users.c.id == role_assignments.c.subject_id,
                                      role_assignments.c.subject_kind == "person"))
            .where(role_assignments.c.role_id == role_id)
            .order_by(users.c.name, role_assignments.c.team_id)
        )  # fmt: skip
        return [
            RoleHolderRow(kind=h.subject_kind, id=h.subject_id, team_id=h.team_id, name=h.name or h.subject_id,
                          email=h.email)
            for h in await rows(c, q, _Held)
        ]  # fmt: skip

    async def version(self, tenant_id: str) -> int:
        async with self.tenant_tx(tenant_id) as c:
            return await version_in(c, tenant_id)

    async def security_team(self, tenant_id: str) -> str | None:
        """The workspace's Security team, from its record; None when it names none."""
        async with self.tenant_tx(tenant_id) as c:
            return (await c.execute(sa.select(tenants.c.security_team_id).where(tenants.c.id == tenant_id))).scalar()


async def grids_in(c: AsyncConnection, role_ids: list[str]) -> dict[str, list[Grant]]:
    """What each role grants, as `effective_grids` answers it from the stored rows: a built-in role with no rows
    answers its seed. Every reader here (the live check, the token's grids, the group guard, the roles page, who holds
    a cell) reads through it or `named_grids`."""
    q = (
        sa.select(
            role_permissions.c.role_id, role_permissions.c.area, role_permissions.c.action, role_permissions.c.scope
        )
        .where(role_permissions.c.role_id.in_(role_ids))
        .order_by(role_permissions.c.role_id, role_permissions.c.area, role_permissions.c.action)
    )
    return _effective((await c.execute(q)).all(), role_ids)


async def named_grids(c: AsyncConnection) -> tuple[list[tuple[str, str]], dict[str, list[Grant]]]:
    """Every role of the tenant as (id, name), built-in first then by name, and what each grants as `grids_in` answers
    it, in one statement."""
    q = (
        sa.select(
            roles.c.id,
            roles.c.name,
            role_permissions.c.area,
            role_permissions.c.action,
            role_permissions.c.scope,
        )
        .select_from(roles.outerjoin(role_permissions, role_permissions.c.role_id == roles.c.id))
        .order_by(roles.c.builtin.desc(), roles.c.name, roles.c.id, role_permissions.c.area, role_permissions.c.action)
    )
    found = (await c.execute(q)).all()
    named = list(dict.fromkeys((str(r.id), str(r.name)) for r in found))
    cells = [(r.id, r.area, r.action, r.scope) for r in found if r.area is not None]
    return named, _effective(cells, [i for i, _ in named])


def _effective(cells: Sequence[Any], role_ids: list[str]) -> dict[str, list[Grant]]:
    """(role id, area, action, scope) rows read through `effective_grids`."""
    out: dict[str, list[Grant]] = {}
    for role_id, area, action, scope in cells:
        out.setdefault(str(role_id), []).append((str(area), str(action), "own" if scope == "own" else "all"))
    return {r: list(g) for r, g in effective_grids(out, [r for r in role_ids if r in out or r in BUILTIN_IDS]).items()}


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
    version = await version_in(c, tenant_id)
    security = (await c.execute(sa.select(tenants.c.security_team_id).where(tenants.c.id == tenant_id))).scalar()

    async def fetch(_t: str, _v: int, ids: list[str]) -> dict[str, list[Grant]]:
        return await grids_in(c, ids)

    # The built-in roles too, so a refusal names who holds the cell in this workspace.
    builtins = [r.id for r in BUILTIN_ROLES]
    return await access_from(
        tenant_id, user_id, held, version=version, security=security, fetch=fetch, also=builtins, team=team
    )


async def access_from(
    tenant_id: str,
    user_id: str,
    held: Holdings,
    *,
    version: int,
    security: str | None,
    fetch: FetchGrids,
    also: list[str] | None = None,
    team: str | None = None,
) -> tuple[Principal, Access]:
    """The person as `can` sees them, from rows already read: their holdings, the permission version, the Security
    team and the grids `fetch` answers for the roles they hold (and `also`), loaded once."""
    live = active(held.assignments, now_iso())
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
    access = Access(security_team=security, grids=Grids(fetch=fetch))
    await access.grids.load(tenant_id, version, [*{a.role_id for a in live}, *(also or [])])
    # Loaded once; a later load would read on a transaction that has ended.
    access.grids.fetch = None
    return p, access


def is_workspace_admin(p: Principal, access: Access) -> bool:
    """The one decision of who is a workspace admin: `access.manage` through a role assigned in every team (`*`), so
    they act in any team whether or not they belong to it. `RoleStore.workspace_admin` and `/v1/me` both ask it."""
    # `from_any_team`: the token-less caller acts in no team, and `roles_in(p, "*")` reads only `*` assignments.
    return access.may(p, "access", "manage", team=ANY_TEAM, from_any_team=True)


async def holdings_in(c: AsyncConnection, user_id: str) -> Holdings:
    """`RoleStore.holdings` on the caller's transaction: the person's active member teams, then `holdings_with`."""
    mine = (
        sa.select(teams.c.id, teams.c.name)
        .join(members, members.c.team_id == teams.c.id)
        .where(members.c.user_id == user_id, members.c.status == "active", teams.c.status == "active")
    )
    return await holdings_with(c, user_id, {str(r[0]): str(r[1]) for r in (await c.execute(mine)).all()})


async def holdings_with(c: AsyncConnection, user_id: str, names: dict[str, str]) -> Holdings:
    """The one holdings read, given the person's active member teams (id to name): the assignments made to them, to one
    of those teams or to a group they are in, and the names of teams only an assignment names. An assignment counts only
    in every team (`*`) or in an active team: an archived team's, or one whose row is gone, grants nothing, since
    acting there answers 403. A group's assignment of a role that holds a privileged cell where it is given counts for
    nothing, whenever the role gained the cell. `/v1/me`, `/v1/me/permissions` and the token's `access` claim all
    read it."""
    groups = sa.select(group_members.c.group_id).where(group_members.c.user_id == user_id)
    subject = sa.or_(
        sa.and_(role_assignments.c.subject_kind == "person", role_assignments.c.subject_id == user_id),
        sa.and_(role_assignments.c.subject_kind == "team", role_assignments.c.subject_id.in_(list(names))),
        sa.and_(role_assignments.c.subject_kind == "group", role_assignments.c.subject_id.in_(groups)),
    )
    q = (
        sa.select(
            role_assignments.c.role_id,
            roles.c.name,
            role_assignments.c.team_id,
            role_assignments.c.subject_kind,
            role_assignments.c.expires_at,
            teams.c.name,
            role_assignments.c.tenant_id,
        )
        .join(roles, roles.c.id == role_assignments.c.role_id)
        .outerjoin(teams, teams.c.id == role_assignments.c.team_id)
        .where(subject, sa.or_(role_assignments.c.team_id == ANY_TEAM, teams.c.status == "active"))
        .order_by(role_assignments.c.created_at, role_assignments.c.id)
    )
    rows = (await c.execute(q)).all()
    by_group = [r for r in rows if r[3] == "group"]
    if by_group:
        grids = await grids_in(c, sorted({str(r[0]) for r in by_group}))
        security = (
            await c.execute(sa.select(tenants.c.security_team_id).where(tenants.c.id == by_group[0][6]))
        ).scalar()
        rows = [
            r
            for r in rows
            if r[3] != "group" or not privileged_cells(grids.get(str(r[0]), []), team=str(r[2]), security_team=security)
        ]
    # A team named by an assignment but not a membership still needs its name.
    names = {**names, **{str(r[2]): str(r[5]) for r in rows if r[5] is not None and str(r[2]) not in names}}
    assignments = [Assignment(str(r[0]), str(r[1]), str(r[2]), r[3], r[4]) for r in rows]
    return Holdings(teams=names, assignments=assignments)


async def _refuse_privileged_for_group(c: AsyncConnection, tenant_id: str, role_id: str, team_id: str) -> None:
    grants = (await grids_in(c, [role_id])).get(role_id, [])
    security = (await c.execute(sa.select(tenants.c.security_team_id).where(tenants.c.id == tenant_id))).scalar()
    if cells := privileged_cells(grants, team=team_id, security_team=security):
        raise PrivilegedForGroupError(cells)


async def version_in(c: AsyncConnection, tenant_id: str) -> int:
    found = (await c.execute(sa.select(tenants.c.permission_version).where(tenants.c.id == tenant_id))).scalar()
    return int(found or 0)


async def bump_version(c: AsyncConnection, tenant_id: str) -> None:
    await c.execute(
        tenants.update().where(tenants.c.id == tenant_id).values(permission_version=tenants.c.permission_version + 1)
    )


async def ensure_builtin_roles(c: AsyncConnection, tenant_id: str, *, at: str) -> None:
    """The seven built-in roles and their grid for a tenant made after migration 0006 (the dev seed, tests). Rows that
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


def membership_admins() -> sa.Select[str, str]:
    """Each (team, person) whose membership in that team gives the built-in Admin role. Admin given on its own, by a
    grant, is not a team admin here: a team's admin count and the Security mirror follow memberships (E17)."""
    return sa.select(role_assignments.c.team_id, role_assignments.c.subject_id.label("user_id")).where(
        role_assignments.c.subject_kind == "person",
        role_assignments.c.source == MEMBERSHIP,
        role_assignments.c.role_id == ADMIN.id,
    )


def team_admins(team_id: str) -> sa.ColumnElement[bool]:
    """Which `members` rows are the team's admins: its active members whose membership gives the built-in Admin, read
    from the role assignments through `membership_admins`, as the team's admin count and the Security mirror read them.
    The last-admin guards lock these rows. A grant of Admin, an invite as admin and a removed admin are not counted."""
    held = membership_admins().with_only_columns(role_assignments.c.subject_id)
    return sa.and_(
        members.c.team_id == team_id,
        members.c.status == "active",
        members.c.user_id.in_(held.where(role_assignments.c.team_id == team_id)),
    )


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


async def holds_admin(c: AsyncConnection, tenant_id: str, user_id: str) -> bool:
    """Whether the person may manage access in any team they hold a role in, or in every team, or is on the break-glass
    list: none of them is ever linked to a provider by the email it asserts. Decided by the cell through `can`, so a
    custom role holding `access.manage` counts as Admin does."""
    listed = sa.select(signin_break_glass.c.user_id).where(signin_break_glass.c.user_id == user_id)
    if (await c.execute(listed)).first() is not None:
        return True
    p, access = await live_in(c, tenant_id, user_id)
    held = {*p.team_ids, *p.access}
    return any(access.may(p, "access", "manage", team=t, from_any_team=True) for t in held)
