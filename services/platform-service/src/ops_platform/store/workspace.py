"""A workspace's own teams (c-202): which team is its security team and which one people join when nothing else names
one. Null columns keep the deployment's defaults: the security team from settings and no default team.

Every reader calls `security_team_in` on the connection of the transaction it decides in, so a change of security team
is seen at once. A change re-mirrors the admins of the old and the new security team in its own transaction, so
Security admin moves with it and nobody holds it in two teams or in none, and the permission version rises.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_store import Guarantee

from .audit import record
from .roles import bump_version, mirror_membership
from .tables import members, teams, tenants
from .tenancy import TenantDb


async def security_team_in(c: AsyncConnection, tenant_id: str, fallback: str) -> str:
    q = sa.select(tenants.c.security_team_id).where(tenants.c.id == tenant_id)
    return (await c.execute(q)).scalar() or fallback


async def default_team_in(c: AsyncConnection, tenant_id: str) -> str | None:
    """The workspace's default team, when it is still active."""
    q = (
        sa.select(teams.c.id)
        .join(tenants, tenants.c.default_team_id == teams.c.id)
        .where(tenants.c.id == tenant_id, teams.c.status == "active")
    )
    return (await c.execute(q)).scalar()


@dataclass(frozen=True)
class WorkspaceTeams:
    security_team: str
    default_team: str | None


class TeamNotUsableError(Exception):
    """The team is not an active team of this workspace."""


class WorkspaceStore:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    def __init__(self, db: TenantDb, *, fallback_security_team: str) -> None:
        self.db = db
        self.fallback = fallback_security_team

    async def security_team(self, tenant_id: str) -> str:
        async with self.db.tenant_tx(tenant_id) as c:
            return await security_team_in(c, tenant_id, self.fallback)

    async def rename(self, tenant_id: str, name: str, *, by: str, request_id: str) -> str:
        """The workspace's display name, as the console's header and team switcher show it; the change is audited."""
        async with self.db.tenant_tx(tenant_id) as c:
            before = (await c.execute(sa.select(tenants.c.name).where(tenants.c.id == tenant_id))).scalar()
            await c.execute(tenants.update().where(tenants.c.id == tenant_id).values(name=name))
            await record(
                c,
                tenant_id=tenant_id,
                team_id=None,
                actor=by,
                action="workspace.rename",
                target_kind="workspace",
                target_id=tenant_id,
                request_id=request_id,
                detail={"from": before, "to": name},
            )
        return name

    async def read(self, tenant_id: str) -> WorkspaceTeams:
        async with self.db.tenant_tx(tenant_id) as c:
            return WorkspaceTeams(
                await security_team_in(c, tenant_id, self.fallback), await default_team_in(c, tenant_id)
            )

    async def set(
        self, tenant_id: str, *, security_team: str, default_team: str | None, by: str, at: str, request_id: str
    ) -> WorkspaceTeams:
        async with self.db.tenant_tx(tenant_id) as c:
            wanted = {security_team, *([default_team] if default_team else [])}
            found = await c.execute(
                sa.select(teams.c.id).where(teams.c.id.in_(sorted(wanted)), teams.c.status == "active")
            )
            if {str(t) for t in found.scalars()} != wanted:
                raise TeamNotUsableError
            before = await security_team_in(c, tenant_id, self.fallback)
            await c.execute(
                tenants.update()
                .where(tenants.c.id == tenant_id)
                .values(security_team_id=security_team, default_team_id=default_team)
            )
            if before != security_team:
                admins = (
                    await c.execute(
                        sa.select(members.c.team_id, members.c.user_id).where(
                            members.c.team_id.in_([before, security_team]),
                            members.c.status == "active",
                            members.c.role == "admin",
                        )
                    )
                ).all()
                for team_id, user_id in admins:
                    await mirror_membership(
                        c,
                        tenant_id=tenant_id,
                        team_id=str(team_id),
                        user_id=str(user_id),
                        member_role="admin",
                        security_team=security_team,
                        granted_by=by,
                        at=at,
                    )
                await bump_version(c, tenant_id)
            await record(
                c,
                tenant_id=tenant_id,
                team_id=None,
                actor=by,
                action="workspace.teams",
                target_kind="tenant",
                target_id=tenant_id,
                request_id=request_id,
                detail={"securityTeam": security_team, "defaultTeam": default_team, "securityTeamBefore": before},
            )
        return WorkspaceTeams(security_team, default_team)
