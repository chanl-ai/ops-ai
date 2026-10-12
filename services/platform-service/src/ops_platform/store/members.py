"""Teams, members and invites.

Role changes and removals lock the team's active admins (`FOR UPDATE`) before deciding, so two requests that each
demote one of two admins cannot both pass the last-admin rule (I6). A removal ends the person's sessions and disables
the keys they created in that team in the same transaction (I10). An invite is a `members` row with status `invited`
and a hashed token; reading one by token runs in `system_tx`, because the token is what names the tenant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.ids import new_id
from ops_store import Guarantee

from .audit import record
from .tables import api_keys, members, sessions, teams, users
from .tenancy import TenantDb

ADMIN = "admin"


@dataclass(frozen=True)
class Actor:
    tenant_id: str
    team_id: str
    user_id: str
    request_id: str


@dataclass
class Bulk:
    updated: list[str] = field(default_factory=list[str])
    skipped: list[dict[str, str]] = field(default_factory=list[dict[str, str]])

    def skip(self, member_id: str, reason: str) -> None:
        self.skipped.append({"id": member_id, "reason": reason})


@dataclass(frozen=True)
class Invite:
    member_id: str
    tenant_id: str
    team_id: str
    team: str
    email: str
    role: str
    status: str
    invited_at: str
    expires_at: str
    allowed_domains: list[str]


class TeamStore:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.RLS, Guarantee.LOCK})

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def teams_of(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        mine = (
            sa.select(teams.c.id, teams.c.name, teams.c.owner_groups, teams.c.scope, members.c.role)
            .join(members, members.c.team_id == teams.c.id)
            .where(members.c.user_id == user_id, members.c.status == "active")
            .order_by(members.c.created_at, members.c.id)
        )
        counts = (
            sa.select(members.c.team_id, sa.func.count())
            .where(members.c.status == "active")
            .group_by(members.c.team_id)
        )
        async with self.db.tenant_tx(tenant_id) as c:
            rows = (await c.execute(mine)).all()
            sizes = {str(r[0]): int(r[1]) for r in (await c.execute(counts)).all()}
        return [
            {
                "id": r[0],
                "name": r[1],
                "ownerGroups": list(r[2]),
                "scope": r[3],
                "role": r[4],
                "memberCount": sizes.get(str(r[0]), 0),
            }
            for r in rows
        ]

    async def scope_of(self, tenant_id: str, team_id: str) -> str | None:
        async with self.db.tenant_tx(tenant_id) as c:
            return (await c.execute(sa.select(teams.c.scope).where(teams.c.id == team_id))).scalar()

    async def role_in(self, tenant_id: str, team_id: str, user_id: str) -> str | None:
        q = sa.select(members.c.role).where(
            members.c.team_id == team_id, members.c.user_id == user_id, members.c.status == "active"
        )
        async with self.db.tenant_tx(tenant_id) as c:
            return (await c.execute(q)).scalar()

    async def members(
        self, tenant_id: str, team_id: str, *, roles: list[str], statuses: list[str]
    ) -> list[dict[str, Any]]:
        q = (
            sa.select(
                members.c.id,
                sa.func.coalesce(users.c.name, members.c.email),
                members.c.email,
                members.c.role,
                members.c.team_id,
                teams.c.name,
                members.c.status,
                members.c.created_at,
            )
            .join(teams, teams.c.id == members.c.team_id)
            .outerjoin(users, users.c.id == members.c.user_id)
            .where(members.c.team_id == team_id, members.c.status != "removed")
            .order_by(members.c.created_at, members.c.id)
        )
        if roles:
            q = q.where(members.c.role.in_(roles))
        if statuses:
            q = q.where(members.c.status.in_(statuses))
        async with self.db.tenant_tx(tenant_id) as c:
            rows = (await c.execute(q)).all()
        return [
            {
                "id": r[0],
                "name": r[1],
                "email": r[2],
                "role": r[3],
                "teamId": r[4],
                "team": r[5],
                "status": r[6],
                **({"invitedAt": r[7]} if r[6] == "invited" else {}),
            }
            for r in rows
        ]

    async def invite(
        self, actor: Actor, *, invites: dict[str, str], role: str, expires_at: str, at: str
    ) -> tuple[Bulk, list[dict[str, str]]]:
        """`invites` maps each lower-cased email to its token hash. Returns the bulk result and, per new invite, its
        member id and email; the caller pairs those with the plain tokens it kept."""
        bulk, made = Bulk(), list[dict[str, str]]()
        async with self.db.tenant_tx(actor.tenant_id) as c:
            for email, token_hash in invites.items():
                existing = (
                    await c.execute(
                        sa.select(members.c.id, members.c.status).where(
                            members.c.team_id == actor.team_id, sa.func.lower(members.c.email) == email
                        )
                    )
                ).first()
                if existing is not None and existing[1] != "removed":
                    bulk.skip(existing[0], "already_member" if existing[1] == "active" else "already_invited")
                    continue
                values = {
                    "role": role,
                    "status": "invited",
                    "user_id": None,
                    "invite_token_hash": token_hash,
                    "invite_expires_at": expires_at,
                    "updated_at": at,
                }
                if existing is None:
                    member_id = new_id("mem")
                    await c.execute(
                        members.insert().values(
                            id=member_id,
                            tenant_id=actor.tenant_id,
                            team_id=actor.team_id,
                            email=email,
                            created_at=at,
                            **values,
                        )
                    )
                else:
                    member_id = existing[0]
                    await c.execute(members.update().where(members.c.id == member_id).values(created_at=at, **values))
                await _audit(c, actor, "member.invite", member_id, {"email": email, "role": role})
                bulk.updated.append(member_id)
                made.append({"memberId": member_id, "email": email})
        return bulk, made

    async def set_role(self, actor: Actor, ids: list[str], role: str, *, at: str) -> Bulk:
        bulk = Bulk()
        async with self.db.tenant_tx(actor.tenant_id) as c:
            admins = await _lock_admins(c, actor.team_id)
            for member_id in ids:
                row = await _member(c, actor.team_id, member_id)
                if row is None:
                    bulk.skip(member_id, "not_found")
                    continue
                if member_id in admins and role != ADMIN and len(admins) == 1:
                    bulk.skip(member_id, "last_admin")
                    continue
                await c.execute(members.update().where(members.c.id == member_id).values(role=role, updated_at=at))
                if role == ADMIN and row["status"] == "active":
                    admins.add(member_id)
                else:
                    admins.discard(member_id)
                await _audit(c, actor, "member.role", member_id, {"from": row["role"], "to": role})
                bulk.updated.append(member_id)
        return bulk

    async def remove(self, actor: Actor, ids: list[str], *, at: str) -> Bulk:
        bulk = Bulk()
        async with self.db.tenant_tx(actor.tenant_id) as c:
            admins = await _lock_admins(c, actor.team_id)
            for member_id in ids:
                row = await _member(c, actor.team_id, member_id)
                if row is None:
                    bulk.skip(member_id, "not_found")
                    continue
                if member_id in admins and len(admins) == 1:
                    bulk.skip(member_id, "last_admin")
                    continue
                await c.execute(
                    members.update()
                    .where(members.c.id == member_id)
                    .values(status="removed", invite_token_hash=None, updated_at=at)
                )
                admins.discard(member_id)
                user_id = row["user_id"]
                if user_id is not None:
                    # I10: their sessions end now, and keys they made for this team stop working.
                    await c.execute(
                        sessions.update()
                        .where(sessions.c.user_id == user_id, sessions.c.revoked_at.is_(None))
                        .values(revoked_at=at)
                    )
                    await c.execute(
                        api_keys.update()
                        .where(
                            api_keys.c.team_id == actor.team_id,
                            api_keys.c.created_by == user_id,
                            api_keys.c.disabled_at.is_(None),
                        )
                        .values(disabled_at=at)
                    )
                await _audit(c, actor, "member.remove", member_id, {"email": row["email"]})
                bulk.updated.append(member_id)
        return bulk

    async def invite_by_hash(self, token_hash: str) -> Invite | None:
        q = sa.text(
            "SELECT member_id, tenant_id, team_id, team, email, role, status, invited_at, expires_at, allowed_domains"
            " FROM platform_invite(:h)"
        )
        async with self.db.system_tx() as c:
            r = (await c.execute(q, {"h": token_hash})).first()
        if r is None:
            return None
        return Invite(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8] or "", list(r[9]))

    async def accept(self, invite: Invite, *, name: str, at: str, request_id: str) -> str | None:
        """Makes the invited member active, creating the user when the tenant has none with that email. Returns the
        user id, or None when the invite was accepted or withdrawn meanwhile (the status check is in the update)."""
        try:
            return await self._accept(invite, name=name, at=at, request_id=request_id)
        except _AlreadyDone:
            return None

    async def _accept(self, invite: Invite, *, name: str, at: str, request_id: str) -> str:
        async with self.db.tenant_tx(invite.tenant_id) as c:
            user_id = (
                await c.execute(sa.select(users.c.id).where(sa.func.lower(users.c.email) == invite.email.lower()))
            ).scalar()
            if user_id is None:
                user_id = new_id("usr")
                await c.execute(
                    users.insert().values(
                        id=user_id,
                        tenant_id=invite.tenant_id,
                        email=invite.email,
                        name=name,
                        status="active",
                        created_at=at,
                    )
                )
            done = await c.execute(
                members.update()
                .where(members.c.id == invite.member_id, members.c.status == "invited")
                .values(status="active", user_id=user_id, updated_at=at)
            )
            if done.rowcount != 1:
                raise _AlreadyDone  # rolls back the user it may have created
            actor = Actor(invite.tenant_id, invite.team_id, user_id, request_id)
            await _audit(c, actor, "member.accept", invite.member_id, {"email": invite.email})
        return user_id


class _AlreadyDone(Exception):
    pass


async def _lock_admins(c: AsyncConnection, team_id: str) -> set[str]:
    q = (
        sa.select(members.c.id)
        .where(members.c.team_id == team_id, members.c.role == ADMIN, members.c.status == "active")
        .with_for_update()
    )
    return {str(i) for i in (await c.execute(q)).scalars().all()}


async def _member(c: AsyncConnection, team_id: str, member_id: str) -> dict[str, Any] | None:
    q = sa.select(members.c.role, members.c.status, members.c.user_id, members.c.email).where(
        members.c.id == member_id, members.c.team_id == team_id, members.c.status != "removed"
    )
    row = (await c.execute(q)).mappings().first()
    return dict(row) if row else None


async def _audit(c: AsyncConnection, actor: Actor, action: str, member_id: str, detail: dict[str, Any]) -> None:
    await record(
        c,
        tenant_id=actor.tenant_id,
        team_id=actor.team_id,
        actor=actor.user_id,
        action=action,
        target_kind="member",
        target_id=member_id,
        request_id=actor.request_id,
        detail=detail,
    )
