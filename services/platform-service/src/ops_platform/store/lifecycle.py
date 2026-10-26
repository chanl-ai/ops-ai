"""A workspace's and a team's danger zones (c-529): transfer, leave, close, restore and purge a workspace; leave and
delete a team.

The owner is the one person with an Owner assignment in every team (`*`); the partial unique index
`ux_role_assignments_owner` keeps it to one. A transfer deletes the caller's Owner row and inserts the target's in one
transaction, reading the workspace's status under a row lock first, so two transfers, or a transfer and a close, cannot
both win: the second finds no Owner row of its caller to delete.

Nothing here deletes a team or a workspace row: audit entries reference both (`fk_audit_entries_team`). A deleted
team is marked `deleted`, frees its name and loses its members and assignments; a purged workspace keeps `tenants`,
`users`, `teams` and `audit_entries` and loses the rest of platform-service's records. Every change writes its audit
entry in the same transaction and raises the permission version when an assignment changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_access import ANY_TEAM, OWNER
from ops_service_kit.ids import new_id
from ops_store import Guarantee
from ops_store.dialect import locked

from .audit import record
from .members import ADMIN
from .roles import bump_version, mirror_membership
from .tables import (
    api_keys,
    members,
    password_credentials,
    password_resets,
    role_assignments,
    sessions,
    signin_domains,
    signin_flows,
    signin_identities,
    signin_lockouts,
    signin_providers,
    teams,
    tenants,
)
from .tenancy import PURGE_LOOKUP, TenantDb
from .workspace import security_team_in

ACTIVE, CLOSED, PURGING, PURGED = "active", "closed", "purging", "purged"
DELETED = "deleted"


class NotOwnerError(Exception):
    """The caller holds no Owner assignment now: someone else's transfer won, or they never held it."""


class WorkspaceNotActiveError(Exception):
    """The workspace is closed or being purged."""


class PurgeStartedError(Exception):
    """The purge has started, so the workspace cannot be restored."""


class LastAdminError(Exception):
    """The person is the team's last active admin."""


@dataclass(frozen=True)
class WorkspaceState:
    status: str
    closed_at: str | None
    owner: str | None


async def _audit(
    c: AsyncConnection,
    *,
    tenant_id: str,
    team_id: str | None,
    actor: str,
    action: str,
    target_kind: str,
    target_id: str,
    request_id: str,
    detail: dict[str, object] | None = None,
) -> None:
    await record(
        c,
        tenant_id=tenant_id,
        team_id=team_id,
        actor=actor,
        action=action,
        target_kind=target_kind,
        target_id=target_id,
        request_id=request_id,
        detail=dict(detail or {}),
    )


def _owner_rows(tenant_id: str) -> sa.ColumnElement[bool]:
    return sa.and_(
        role_assignments.c.tenant_id == tenant_id,
        role_assignments.c.role_id == OWNER.id,
        role_assignments.c.team_id == ANY_TEAM,
    )


async def _owner_in(c: AsyncConnection, tenant_id: str) -> str | None:
    q = sa.select(role_assignments.c.subject_id).where(
        _owner_rows(tenant_id), role_assignments.c.subject_kind == "person"
    )
    return (await c.execute(q)).scalar()


async def _status_locked(c: AsyncConnection, tenant_id: str) -> str:
    q = locked(sa.select(tenants.c.status).where(tenants.c.id == tenant_id), tenants)
    return str((await c.execute(q)).scalar_one())


class LifecycleStore:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    def __init__(self, db: TenantDb, *, security_team: str) -> None:
        self.db = db
        self.security_team = security_team

    async def state(self, tenant_id: str) -> WorkspaceState:
        async with self.db.tenant_tx(tenant_id) as c:
            row = (
                await c.execute(sa.select(tenants.c.status, tenants.c.closed_at).where(tenants.c.id == tenant_id))
            ).one()
            return WorkspaceState(str(row[0]), row[1], await _owner_in(c, tenant_id))

    async def status(self, tenant_id: str) -> str | None:
        """The workspace's status; None for a tenant this database does not hold."""
        async with self.db.tenant_tx(tenant_id) as c:
            return (await c.execute(sa.select(tenants.c.status).where(tenants.c.id == tenant_id))).scalar()

    async def name(self, tenant_id: str) -> str:
        async with self.db.tenant_tx(tenant_id) as c:
            return str((await c.execute(sa.select(tenants.c.name).where(tenants.c.id == tenant_id))).scalar_one())

    async def transfer(self, tenant_id: str, *, by: str, to: str, at: str, request_id: str) -> None:
        async with self.db.tenant_tx(tenant_id) as c:
            if await _status_locked(c, tenant_id) != ACTIVE:
                raise WorkspaceNotActiveError
            gone = await c.execute(
                role_assignments.delete().where(
                    _owner_rows(tenant_id),
                    role_assignments.c.subject_kind == "person",
                    role_assignments.c.subject_id == by,
                )
            )
            if gone.rowcount != 1:
                raise NotOwnerError
            await c.execute(
                role_assignments.insert().values(
                    id=new_id("ras"), tenant_id=tenant_id, subject_kind="person", subject_id=to, role_id=OWNER.id,
                    team_id=ANY_TEAM, granted_by=by, reason="Workspace transferred", source="grant", created_at=at,
                )
            )  # fmt: skip
            await bump_version(c, tenant_id)
            await _audit(
                c, tenant_id=tenant_id, team_id=None, actor=by, action="workspace.transfer", target_kind="workspace",
                target_id=tenant_id, request_id=request_id, detail={"from": by, "to": to},
            )  # fmt: skip

    async def leave(self, tenant_id: str, *, user_id: str, at: str, request_id: str) -> None:
        """The person loses every team: memberships removed, every assignment of theirs deleted, sessions ended. Their
        account stays, so a later invite reaches the same person."""
        async with self.db.tenant_tx(tenant_id) as c:
            if await _owner_in(c, tenant_id) == user_id:
                raise NotOwnerError  # the route refuses the owner before this; a transfer racing it lands here
            await c.execute(
                members.update()
                .where(members.c.user_id == user_id, members.c.status != "removed")
                .values(status="removed", invite_token_hash=None, updated_at=at)
            )
            await c.execute(
                role_assignments.delete().where(
                    role_assignments.c.tenant_id == tenant_id,
                    role_assignments.c.subject_kind == "person",
                    role_assignments.c.subject_id == user_id,
                )
            )
            await c.execute(
                sessions.update()
                .where(sessions.c.user_id == user_id, sessions.c.revoked_at.is_(None))
                .values(revoked_at=at)
            )
            await c.execute(
                api_keys.update()
                .where(api_keys.c.created_by == user_id, api_keys.c.disabled_at.is_(None))
                .values(disabled_at=at)
            )
            await bump_version(c, tenant_id)
            await _audit(
                c, tenant_id=tenant_id, team_id=None, actor=user_id, action="workspace.leave", target_kind="user",
                target_id=user_id, request_id=request_id,
            )  # fmt: skip

    async def close(self, tenant_id: str, *, by: str, at: str, request_id: str) -> None:
        """Closes at once: every session but the owner's ends and every key stops working, with one `at` so a restore
        re-enables only the keys this close disabled."""
        async with self.db.tenant_tx(tenant_id) as c:
            if await _status_locked(c, tenant_id) != ACTIVE:
                raise WorkspaceNotActiveError
            if await _owner_in(c, tenant_id) != by:
                raise NotOwnerError
            await c.execute(
                tenants.update().where(tenants.c.id == tenant_id).values(status=CLOSED, closed_at=at, closed_by=by)
            )
            await c.execute(
                sessions.update().where(sessions.c.user_id != by, sessions.c.revoked_at.is_(None)).values(revoked_at=at)
            )
            await c.execute(api_keys.update().where(api_keys.c.disabled_at.is_(None)).values(disabled_at=at))
            await _audit(
                c, tenant_id=tenant_id, team_id=None, actor=by, action="workspace.close", target_kind="workspace",
                target_id=tenant_id, request_id=request_id,
            )  # fmt: skip

    async def restore(self, tenant_id: str, *, by: str, request_id: str) -> None:
        async with self.db.tenant_tx(tenant_id) as c:
            status = await _status_locked(c, tenant_id)
            if status != CLOSED:
                raise PurgeStartedError if status in (PURGING, PURGED) else WorkspaceNotActiveError
            closed_at = (await c.execute(sa.select(tenants.c.closed_at).where(tenants.c.id == tenant_id))).scalar()
            await c.execute(
                tenants.update().where(tenants.c.id == tenant_id).values(status=ACTIVE, closed_at=None, closed_by=None)
            )
            await c.execute(api_keys.update().where(api_keys.c.disabled_at == closed_at).values(disabled_at=None))
            await _audit(
                c, tenant_id=tenant_id, team_id=None, actor=by, action="workspace.restore", target_kind="workspace",
                target_id=tenant_id, request_id=request_id,
            )  # fmt: skip

    async def purge_due(self, *, restore_days: int, now: datetime | None = None) -> list[str]:
        """The workspaces closed longer than the window; a pre-tenant lookup (migration 0026's function)."""
        cutoff = (now or datetime.now(UTC)) - timedelta(days=restore_days)
        stamp = cutoff.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        async with self.db.system_tx(PURGE_LOOKUP) as c:
            rows = await c.execute(sa.text("SELECT tenant_id FROM platform_purge_due(:c)"), {"c": stamp})
            return [str(r[0]) for r in rows]

    async def purge(self, tenant_id: str, *, at: str, request_id: str) -> bool:
        """Marks the workspace `purging` in its own transaction, so a restore that comes after is refused, then
        removes platform-service's records of it but its tenant, people, teams, policies and audit entries (the
        tenant role may not delete a policy). False when it is no longer closed (restored in between)."""
        async with self.db.tenant_tx(tenant_id) as c:
            if await _status_locked(c, tenant_id) != CLOSED:
                return False
            await c.execute(tenants.update().where(tenants.c.id == tenant_id).values(status=PURGING))
        async with self.db.tenant_tx(tenant_id) as c:
            for table in (
                sessions, api_keys, role_assignments, members, signin_flows, signin_identities,
                signin_domains, signin_providers, password_resets, password_credentials, signin_lockouts,
            ):  # fmt: skip
                await c.execute(table.delete().where(table.c.tenant_id == tenant_id))
            await c.execute(teams.update().where(teams.c.tenant_id == tenant_id).values(status=DELETED))
            await c.execute(tenants.update().where(tenants.c.id == tenant_id).values(status=PURGED))
            await _audit(
                c, tenant_id=tenant_id, team_id=None, actor="system", action="workspace.purge",
                target_kind="workspace", target_id=tenant_id, request_id=request_id, detail={"at": at},
            )  # fmt: skip
        return True

    async def leave_team(self, tenant_id: str, team_id: str, *, user_id: str, at: str, request_id: str) -> bool:
        """False when the person is not an active member of the team."""
        async with self.db.tenant_tx(tenant_id) as c:
            admins_q = sa.select(members.c.user_id).where(
                members.c.team_id == team_id, members.c.role == ADMIN, members.c.status == "active"
            )
            admins = {str(u) for u in (await c.execute(locked(admins_q, members))).scalars()}
            mine = (
                await c.execute(
                    sa.select(members.c.id).where(
                        members.c.team_id == team_id, members.c.user_id == user_id, members.c.status == "active"
                    )
                )
            ).scalar()
            if mine is None:
                return False
            if admins == {user_id}:
                raise LastAdminError
            await c.execute(
                members.update()
                .where(members.c.id == mine)
                .values(status="removed", invite_token_hash=None, updated_at=at)
            )
            await mirror_membership(
                c, tenant_id=tenant_id, team_id=team_id, user_id=user_id, member_role=None,
                security_team=await security_team_in(c, tenant_id, self.security_team), granted_by=user_id, at=at,
            )  # fmt: skip
            await _audit(
                c, tenant_id=tenant_id, team_id=team_id, actor=user_id, action="team.leave", target_kind="member",
                target_id=str(mine), request_id=request_id,
            )  # fmt: skip
        return True

    async def team_state(self, tenant_id: str, team_id: str) -> tuple[str, str | None] | None:
        """(status, archived at) of a team that is not deleted; None when there is none."""
        async with self.db.tenant_tx(tenant_id) as c:
            row = (
                await c.execute(
                    sa.select(teams.c.status, teams.c.archived_at).where(
                        teams.c.id == team_id, teams.c.status != DELETED
                    )
                )
            ).first()
        return (str(row[0]), row[1]) if row else None

    async def delete_team(
        self, tenant_id: str, team_id: str, *, by: str, archived_before: str, at: str, request_id: str
    ) -> bool:
        """Deletes a team archived at or before `archived_before`: its members and assignments go, its name is free
        again, its row stays. False when the team is not archived that long (restored or deleted in between)."""
        async with self.db.tenant_tx(tenant_id) as c:
            done = await c.execute(
                teams.update()
                .where(teams.c.id == team_id, teams.c.status == "archived", teams.c.archived_at <= archived_before)
                .values(status=DELETED, name_key=f"{DELETED}:{team_id}")
            )
            if done.rowcount != 1:
                return False
            await c.execute(
                members.update()
                .where(members.c.team_id == team_id, members.c.status != "removed")
                .values(status="removed", invite_token_hash=None, updated_at=at)
            )
            await c.execute(
                role_assignments.delete().where(
                    role_assignments.c.tenant_id == tenant_id,
                    sa.or_(
                        role_assignments.c.team_id == team_id,
                        sa.and_(role_assignments.c.subject_kind == "team", role_assignments.c.subject_id == team_id),
                    ),
                )
            )
            await c.execute(
                api_keys.update()
                .where(api_keys.c.team_id == team_id, api_keys.c.disabled_at.is_(None))
                .values(disabled_at=at)
            )
            await bump_version(c, tenant_id)
            await _audit(
                c, tenant_id=tenant_id, team_id=team_id, actor=by, action="team.delete", target_kind="team",
                target_id=team_id, request_id=request_id,
            )  # fmt: skip
        return True
