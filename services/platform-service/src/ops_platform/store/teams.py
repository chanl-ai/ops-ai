"""Teams as a workspace admin manages them: create with a first admin, rename, archive and restore, and every
team of the workspace with its counts.

A create writes the team, its first admin's membership and the role assignments that mirror it in one transaction, so a
team never exists without an admin. The name rule is the `uq_teams_tenant_name` index on the lower-case name, so two
requests racing for one name cannot both win. Each change is audited in its own transaction.
"""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from ops_access.platform_events import TEAM_CREATED
from ops_service_kit.http import Out
from ops_service_kit.ids import new_id
from ops_service_kit.listing import ListParams
from ops_store import Guarantee
from ops_store.listing import ListPage, Rows, list_page
from ops_store.outbox import add as add_event
from ops_store.rows import rows

from .audit import record
from .roles import mirror_membership
from .tables import members, platform_outbox, teams, users
from .tenancy import TenantDb
from .workspace import security_team_in

ACTIVE, ARCHIVED = "active", "archived"


class TeamNameTakenError(Exception):
    """Another team of the workspace has this name in some case."""


class TeamRow(Out):
    """A team with its active member and admin counts, and whether it is the workspace's Security team."""

    id: str
    name: str
    status: str
    scope: str
    created_at: str
    archived_at: str | None
    member_count: int
    admin_count: int
    security: bool


def _listing(statuses: list[str], security: str | None) -> Rows:
    """The workspace's teams with each one's active member and admin counts; teams first, so a list pages by its id.
    A deleted team keeps its row for its audit entries and is out of every list."""
    counts = (
        sa.select(
            members.c.team_id,
            sa.func.count().label("n"),
            sa.func.sum(sa.case((members.c.role == "admin", 1), else_=0)).label("admins"),
        )
        .where(members.c.status == "active")
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
            sa.func.coalesce(counts.c.n, 0).label("member_count"),
            sa.func.coalesce(counts.c.admins, 0).label("admin_count"),
            sa.case((teams.c.id == security, True), else_=False).label("security"),
        )
        .select_from(teams.outerjoin(counts, counts.c.team_id == teams.c.id))
        .where(teams.c.status != "deleted")
    )
    return q.where(teams.c.status.in_(statuses)) if statuses else q


class TeamAdminStore(TenantDb):
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    async def page(self, tenant_id: str, params: ListParams, *, statuses: list[str]) -> ListPage:
        """The workspace's teams on the shared list contract, by name then id, searched on name, each with its active
        member and admin counts and whether it is the Security team, all in SQL on one transaction."""
        async with self.tenant_tx(tenant_id) as c:
            q = _listing(statuses, await security_team_in(c, tenant_id))
            page = await list_page(c, q, params, search=[teams.c.name_key], default_sort=teams.c.name_key.asc())
        page["data"] = [TeamRow.model_validate(r).model_dump(by_alias=True) for r in page["data"]]
        return page

    async def every(self, tenant_id: str, *, statuses: list[str], team_id: str | None = None) -> list[TeamRow]:
        """Every team of the workspace with its counts, by name, or the one team `team_id` names."""
        async with self.tenant_tx(tenant_id) as c:
            q = _listing(statuses, await security_team_in(c, tenant_id))
            if team_id is not None:
                q = q.where(teams.c.id == team_id)
            return await rows(c, q.order_by(teams.c.name_key, teams.c.id), TeamRow)

    async def one(self, tenant_id: str, team_id: str) -> TeamRow | None:
        rows = await self.every(tenant_id, statuses=[], team_id=team_id)
        return rows[0] if rows else None

    async def create(
        self, tenant_id: str, *, name: str, admin_email: str, by: str, at: str, request_id: str
    ) -> str | None:
        """The new team's id, or None when no active person of the workspace has `admin_email`. Raises
        `TeamNameTakenError` when the name is taken."""
        team_id = new_id("team")
        try:
            async with self.tenant_tx(tenant_id) as c:
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
                    security_team=await security_team_in(c, tenant_id),
                    granted_by=by,
                    at=at,
                )
                # Each service writes the new team's defaults when it hears this: in the transaction that
                # makes the team, so neither commits without the other, and relayed until heard.
                await add_event(
                    c,
                    platform_outbox,
                    tenant_id=tenant_id,
                    team_id=team_id,
                    name=TEAM_CREATED,
                    key=team_id,
                    payload={},
                    actor=by,
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
            async with self.tenant_tx(tenant_id) as c:
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

    async def security_team_of(self, tenant_id: str) -> str | None:
        async with self.tenant_tx(tenant_id) as c:
            return await security_team_in(c, tenant_id)

    async def set_status(self, tenant_id: str, team_id: str, status: str, *, by: str, at: str, request_id: str) -> bool:
        """Archives or restores the team; False when the workspace has no such team."""
        async with self.tenant_tx(tenant_id) as c:
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
