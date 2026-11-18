"""A workspace's and a team's danger zones: transfer, leave, close, restore and purge a workspace; leave and
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

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_access import ANY_TEAM, OWNER
from ops_service_kit.http import Out
from ops_service_kit.ids import new_id
from ops_store import Guarantee
from ops_store.dialect import locked
from ops_store.rows import one

from .audit import record, record_grants_ending
from .key_events import change_keys, delete_keys
from .lookups import PURGE_DUE, lookup
from .roles import bump_version, mirror_membership, team_admins
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


class _TenantStatus(Out):
    status: str
    closed_at: str | None


class WorkspaceState(Out):
    status: str
    closed_at: str | None
    owner: str | None


class TeamState(Out):
    """A team that is not deleted: `active` or `archived`, and when it was archived."""

    status: str
    archived_at: str | None


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
    detail: Mapping[str, JsonValue] | None = None,
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


def owner_query(tenant_id: str) -> sa.Select[Any]:
    """The workspace owner's user id, as a statement another read can embed."""
    return sa.select(role_assignments.c.subject_id).where(
        _owner_rows(tenant_id), role_assignments.c.subject_kind == "person"
    )


async def _owner_in(c: AsyncConnection, tenant_id: str) -> str | None:
    return (await c.execute(owner_query(tenant_id))).scalar()


async def _status_locked(c: AsyncConnection, tenant_id: str) -> str:
    q = locked(sa.select(tenants.c.status).where(tenants.c.id == tenant_id), tenants)
    return str((await c.execute(q)).scalar_one())


class LifecycleStore(TenantDb):
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS})

    async def state(self, tenant_id: str) -> WorkspaceState:
        async with self.tenant_tx(tenant_id) as c:
            row = await one(
                c, sa.select(tenants.c.status, tenants.c.closed_at).where(tenants.c.id == tenant_id), _TenantStatus
            )
            if row is None:
                raise NoResultFound(f"no tenant {tenant_id}")
            return WorkspaceState(status=row.status, closed_at=row.closed_at, owner=await _owner_in(c, tenant_id))

    async def status(self, tenant_id: str) -> str | None:
        """The workspace's status; None for a tenant this database does not hold."""
        async with self.tenant_tx(tenant_id) as c:
            return (await c.execute(sa.select(tenants.c.status).where(tenants.c.id == tenant_id))).scalar()

    async def name(self, tenant_id: str) -> str:
        async with self.tenant_tx(tenant_id) as c:
            return str((await c.execute(sa.select(tenants.c.name).where(tenants.c.id == tenant_id))).scalar_one())

    async def transfer(self, tenant_id: str, *, by: str, to: str, at: str, request_id: str) -> None:
        async with self.tenant_tx(tenant_id) as c:
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
        async with self.tenant_tx(tenant_id) as c:
            if await _owner_in(c, tenant_id) == user_id:
                raise NotOwnerError  # the owner leaves only by a transfer (E42); checked here, before any write
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
            await record_grants_ending(
                c, tenant_id=tenant_id, user_id=user_id, actor=user_id, by="person", request_id=request_id
            )
            await c.execute(
                sessions.update()
                .where(sessions.c.user_id == user_id, sessions.c.revoked_at.is_(None))
                .values(revoked_at=at)
            )
            await change_keys(
                c, sa.and_(api_keys.c.created_by == user_id, api_keys.c.disabled_at.is_(None)), {"disabled_at": at}
            )
            await bump_version(c, tenant_id)
            await _audit(
                c, tenant_id=tenant_id, team_id=None, actor=user_id, action="workspace.leave", target_kind="user",
                target_id=user_id, request_id=request_id,
            )  # fmt: skip

    async def close(self, tenant_id: str, *, by: str, at: str, request_id: str) -> None:
        """Closes at once: every session but the owner's ends and every key stops working, with one `at` so a restore
        re-enables only the keys this close disabled."""
        async with self.tenant_tx(tenant_id) as c:
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
            await change_keys(c, api_keys.c.disabled_at.is_(None), {"disabled_at": at})
            await _audit(
                c, tenant_id=tenant_id, team_id=None, actor=by, action="workspace.close", target_kind="workspace",
                target_id=tenant_id, request_id=request_id,
            )  # fmt: skip

    async def restore(self, tenant_id: str, *, by: str, request_id: str) -> None:
        async with self.tenant_tx(tenant_id) as c:
            status = await _status_locked(c, tenant_id)
            if status != CLOSED:
                raise PurgeStartedError if status in (PURGING, PURGED) else WorkspaceNotActiveError
            closed_at = (await c.execute(sa.select(tenants.c.closed_at).where(tenants.c.id == tenant_id))).scalar()
            await c.execute(
                tenants.update().where(tenants.c.id == tenant_id).values(status=ACTIVE, closed_at=None, closed_by=None)
            )
            await change_keys(c, api_keys.c.disabled_at == closed_at, {"disabled_at": None})
            await _audit(
                c, tenant_id=tenant_id, team_id=None, actor=by, action="workspace.restore", target_kind="workspace",
                target_id=tenant_id, request_id=request_id,
            )  # fmt: skip

    async def purge_due(self, *, restore_days: int, now: datetime | None = None) -> list[str]:
        """The workspaces closed longer than the window; a pre-tenant lookup (migration 0026's function)."""
        cutoff = (now or datetime.now(UTC)) - timedelta(days=restore_days)
        stamp = cutoff.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        async with self.system_tx(PURGE_LOOKUP) as c:
            return [str(r[0]) for r in await lookup(c, PURGE_DUE, stamp)]

    async def purge(self, tenant_id: str, *, at: str, request_id: str) -> bool:
        """Marks the workspace `purging` in its own transaction, so a restore that comes after is refused, then
        removes platform-service's records of it but its tenant, people, teams, policies and audit entries (the
        tenant role may not delete a policy). False when it is no longer closed (restored in between)."""
        async with self.tenant_tx(tenant_id) as c:
            if await _status_locked(c, tenant_id) != CLOSED:
                return False
            await c.execute(tenants.update().where(tenants.c.id == tenant_id).values(status=PURGING))
        async with self.tenant_tx(tenant_id) as c:
            await delete_keys(c, api_keys.c.tenant_id == tenant_id)
            for table in (
                sessions, role_assignments, members, signin_flows, signin_identities,
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
        async with self.tenant_tx(tenant_id) as c:
            admins_q = locked(sa.select(members.c.user_id).where(team_admins(team_id)), members)
            admins = {str(u) for u in (await c.execute(admins_q)).scalars()}
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
                security_team=await security_team_in(c, tenant_id), granted_by=user_id, at=at,
            )  # fmt: skip
            await _audit(
                c, tenant_id=tenant_id, team_id=team_id, actor=user_id, action="team.leave", target_kind="member",
                target_id=str(mine), request_id=request_id,
            )  # fmt: skip
        return True

    async def team_state(self, tenant_id: str, team_id: str) -> TeamState | None:
        """The team's state; None when there is none or it is deleted."""
        q = sa.select(teams.c.status, teams.c.archived_at).where(teams.c.id == team_id, teams.c.status != DELETED)
        async with self.tenant_tx(tenant_id) as c:
            return await one(c, q, TeamState)

    async def delete_team(
        self, tenant_id: str, team_id: str, *, by: str, archived_before: str, at: str, request_id: str
    ) -> bool:
        """Deletes a team archived at or before `archived_before`: its members and assignments go, its name is free
        again, its row stays. False when the team is not archived that long (restored or deleted in between)."""
        async with self.tenant_tx(tenant_id) as c:
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
            await change_keys(
                c, sa.and_(api_keys.c.team_id == team_id, api_keys.c.disabled_at.is_(None)), {"disabled_at": at}
            )
            await bump_version(c, tenant_id)
            await _audit(
                c, tenant_id=tenant_id, team_id=team_id, actor=by, action="team.delete", target_kind="team",
                target_id=team_id, request_id=request_id,
            )  # fmt: skip
        return True
