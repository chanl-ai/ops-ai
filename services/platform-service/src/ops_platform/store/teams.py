"""Teams as a workspace admin manages them (c-198): create with a first admin, rename, archive and restore, and every
team of the workspace with its counts.

A create writes the team, its first admin's membership and the role assignments that mirror it in one transaction, so a
team never exists without an admin. The name rule is the `uq_teams_tenant_name` index on the lower-case name, so two
requests racing for one name cannot both win. Each change is audited in its own transaction.
"""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from ops_service_kit.http import page_window
from ops_service_kit.ids import new_id
from ops_store import Guarantee

from .audit import record
from .roles import mirror_membership
from .tables import members, teams, users
from .tenancy import TenantDb
from .workspace import security_team_in

ACTIVE, ARCHIVED = "active", "archived"


class TeamNameTakenError(Exception):
    """Another team of the workspace has this name in some case."""


class TeamAdminStore:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    def __init__(self, db: TenantDb, *, security_team: str) -> None:
        self.db = db
        self.security_team = security_team

    async def every(
        self,
        tenant_id: str,
        *,
        statuses: list[str],
        search: str = "",
        page: int = 1,
        page_size: int = 50,
        team_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int, int]:
        """One page of the workspace's teams, active first then by name, with each one's active member and admin
        counts; returns the rows, the total and the page answered."""
        active = members.c.status == "active"
        counts = (
            sa.select(
                members.c.team_id,
                sa.func.count().label("n"),
                sa.func.sum(sa.case((members.c.role == "admin", 1), else_=0)).label("admins"),
            )
            .where(active)
            .group_by(members.c.team_id)
            .subquery()
        )
        q = (
            sa.select(
                teams.c.id,
                teams.c.name,
                teams.c.status,
                teams.c.scope,
                teams.c.created_at,
                teams.c.archived_at,
                sa.func.coalesce(counts.c.n, 0),
                sa.func.coalesce(counts.c.admins, 0),
            )
            .outerjoin(counts, counts.c.team_id == teams.c.id)
            .order_by(teams.c.status, teams.c.name_key, teams.c.id)
        )
        where: list[sa.ColumnElement[bool]] = []
        if statuses:
            where.append(teams.c.status.in_(statuses))
        if team_id is not None:
            where.append(teams.c.id == team_id)
        if search:
            escaped = search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append(teams.c.name_key.like(f"%{escaped}%", escape="\\"))
        async with self.db.tenant_tx(tenant_id) as c:
            security = await security_team_in(c, tenant_id, self.security_team)
            total = int((await c.execute(sa.select(sa.func.count()).select_from(teams).where(*where))).scalar_one())
            page, offset = page_window(total, page, page_size)
            rows = (await c.execute(q.where(*where).limit(page_size).offset(offset))).all()
        out = [
            {
                "id": r[0],
                "name": r[1],
                "status": r[2],
                "scope": r[3],
                "createdAt": r[4],
                "archivedAt": r[5],
                "memberCount": int(r[6]),
                "adminCount": int(r[7]),
                "security": r[0] == security,
            }
            for r in rows
        ]
        return out, total, page

    async def one(self, tenant_id: str, team_id: str) -> dict[str, Any] | None:
        rows, _, _ = await self.every(tenant_id, statuses=[], team_id=team_id)
        return rows[0] if rows else None

    async def create(
        self, tenant_id: str, *, name: str, admin_email: str, by: str, at: str, request_id: str
    ) -> str | None:
        """The new team's id, or None when no active person of the workspace has `admin_email`. Raises
        `TeamNameTakenError` when the name is taken."""
        team_id = new_id("team")
        try:
            async with self.db.tenant_tx(tenant_id) as c:
                person = (
                    await c.execute(
                        sa.select(users.c.id, users.c.email).where(
                            sa.func.lower(users.c.email) == admin_email.strip().lower(), users.c.status == "active"
                        )
                    )
                ).first()
                if person is None:
                    return None
                admin_id = str(person[0])
                await c.execute(
                    teams.insert().values(
                        id=team_id,
                        tenant_id=tenant_id,
                        name=name,
                        name_key=name.lower(),
                        owner_groups=[],
                        scope="owned",
                        status=ACTIVE,
                        created_at=at,
                    )
                )
                await c.execute(
                    members.insert().values(
                        id=new_id("mem"),
                        tenant_id=tenant_id,
                        team_id=team_id,
                        user_id=admin_id,
                        email=str(person[1]),
                        role="admin",
                        status="active",
                        created_at=at,
                        updated_at=at,
                    )
                )
                await mirror_membership(
                    c,
                    tenant_id=tenant_id,
                    team_id=team_id,
                    user_id=admin_id,
                    member_role="admin",
                    security_team=await security_team_in(c, tenant_id, self.security_team),
                    granted_by=by,
                    at=at,
                )
                await record(
                    c,
                    tenant_id=tenant_id,
                    team_id=team_id,
                    actor=by,
                    action="team.create",
                    target_kind="team",
                    target_id=team_id,
                    request_id=request_id,
                    detail={"name": name, "admin": admin_id},
                )
        except IntegrityError as e:
            if "uq_teams_tenant_name" in str(e.orig):
                raise TeamNameTakenError from e
            raise
        return team_id

    async def rename(self, tenant_id: str, team_id: str, name: str, *, by: str, at: str, request_id: str) -> bool:
        try:
            async with self.db.tenant_tx(tenant_id) as c:
                before = (await c.execute(sa.select(teams.c.name).where(teams.c.id == team_id))).scalar()
                if before is None:
                    return False
                await c.execute(teams.update().where(teams.c.id == team_id).values(name=name, name_key=name.lower()))
                await record(
                    c,
                    tenant_id=tenant_id,
                    team_id=team_id,
                    actor=by,
                    action="team.rename",
                    target_kind="team",
                    target_id=team_id,
                    request_id=request_id,
                    detail={"from": before, "to": name},
                )
        except IntegrityError as e:
            if "uq_teams_tenant_name" in str(e.orig):
                raise TeamNameTakenError from e
            raise
        return True

    async def security_team_of(self, tenant_id: str) -> str:
        async with self.db.tenant_tx(tenant_id) as c:
            return await security_team_in(c, tenant_id, self.security_team)

    async def set_status(self, tenant_id: str, team_id: str, status: str, *, by: str, at: str, request_id: str) -> bool:
        """Archives or restores the team; False when the workspace has no such team."""
        async with self.db.tenant_tx(tenant_id) as c:
            done = await c.execute(
                teams.update()
                .where(teams.c.id == team_id)
                .values(status=status, archived_at=at if status == ARCHIVED else None)
            )
            if done.rowcount != 1:
                return False
            await record(
                c,
                tenant_id=tenant_id,
                team_id=team_id,
                actor=by,
                action="team.archive" if status == ARCHIVED else "team.restore",
                target_kind="team",
                target_id=team_id,
                request_id=request_id,
                detail={},
            )
        return True
