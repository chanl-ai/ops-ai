"""Teams, members and invites.

Role changes and removals lock the team's active admins (`FOR UPDATE`) before deciding, so two requests that each demote
one of two admins cannot both pass the last-admin rule (I6). A removal ends the person's sessions and disables the keys
they created in that team in the same transaction (I10). Each change to an active membership also rewrites the built-in
role assignments that mirror it (`roles.mirror_membership`) in the same transaction. An invite is a `members` row with
status `invited` and a hashed token; reading one by token runs in `system_tx`, because the token is what names the
tenant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.ids import new_id
from ops_store import Guarantee

from .audit import record
from .roles import mirror_membership
from .tables import api_keys, audit_entries, members, sessions, teams, users
from .tenancy import TenantDb
from .workspace import security_team_in

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

    def __init__(self, db: TenantDb, *, security_team: str = "team_security") -> None:
        self.db = db
        # The deployment's security team (settings `security_team_id`), for a workspace that names none (c-202).
        self.security_team = security_team

    async def people_names(self, tenant_id: str) -> list[dict[str, str]]:
        """Every person of the workspace as `{email, name}`, suspended ones too: a record keeps naming who acted."""
        async with self.db.tenant_tx(tenant_id) as c:
            rows = (await c.execute(sa.select(users.c.email, users.c.name).order_by(users.c.email))).all()
        return [{"email": str(r.email), "name": str(r.name)} for r in rows]

    async def names(self, tenant_id: str) -> list[dict[str, str]]:
        """Every team of the workspace, archived ones too, as `{id, name}` by name: a record keeps naming its team."""
        async with self.db.tenant_tx(tenant_id) as c:
            rows = (await c.execute(sa.select(teams.c.id, teams.c.name).order_by(teams.c.name, teams.c.id))).all()
        return [{"id": str(r.id), "name": str(r.name)} for r in rows]

    async def _mirror(self, c: AsyncConnection, actor: Actor, user_id: str, role: str | None, at: str) -> None:
        await mirror_membership(
            c,
            tenant_id=actor.tenant_id,
            team_id=actor.team_id,
            user_id=user_id,
            member_role=role,
            security_team=await security_team_in(c, actor.tenant_id, self.security_team),
            granted_by=actor.user_id,
            at=at,
        )

    async def security_team_of(self, tenant_id: str) -> str:
        async with self.db.tenant_tx(tenant_id) as c:
            return await security_team_in(c, tenant_id, self.security_team)

    async def teams_of(self, tenant_id: str, user_id: str, *, everywhere: bool = False) -> list[dict[str, Any]]:
        """The person's active teams with their role; `everywhere` (a workspace admin, c-208) adds every other active
        team of the workspace with the role `admin` they hold there through their workspace role."""
        mine = (
            sa.select(teams.c.id, teams.c.name, teams.c.owner_groups, teams.c.scope, members.c.role)
            .join(members, members.c.team_id == teams.c.id)
            .where(members.c.user_id == user_id, members.c.status == "active", teams.c.status == "active")
            .order_by(members.c.created_at, members.c.id)
        )
        counts = (
            sa.select(members.c.team_id, sa.func.count())
            .where(members.c.status == "active")
            .group_by(members.c.team_id)
        )
        async with self.db.tenant_tx(tenant_id) as c:
            rows = list((await c.execute(mine)).all())
            sizes = {str(r[0]): int(r[1]) for r in (await c.execute(counts)).all()}
            if everywhere:
                member_of = {str(r[0]) for r in rows}
                others = sa.select(teams.c.id, teams.c.name, teams.c.owner_groups, teams.c.scope, sa.literal("admin"))
                others = others.where(teams.c.status == "active").order_by(teams.c.created_at, teams.c.id)
                rows += [r for r in (await c.execute(others)).all() if str(r[0]) not in member_of]
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
                members.c.user_id,
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
                "userId": r[8],
                **({"invitedAt": r[7]} if r[6] == "invited" else {}),
            }
            for r in rows
        ]

    async def people_options(
        self, tenant_id: str, team_id: str, *, search: str | None, ids: list[str], offset: int, limit: int
    ) -> list[dict[str, Any]]:
        """The team's active people as picker choices, searched and paged here: the value is the email (assignments
        match a person by email), the label their name. `ids` resolves stored emails to their names."""
        name = sa.func.coalesce(users.c.name, members.c.email)
        q = (
            sa.select(members.c.email, name)
            .outerjoin(users, users.c.id == members.c.user_id)
            .where(members.c.team_id == team_id, members.c.status == "active")
            .order_by(name, members.c.email)
        )
        if ids:
            q = q.where(sa.func.lower(members.c.email).in_([i.lower() for i in ids]))
        elif search:
            like = f"%{search.strip().lower()}%"
            q = q.where(sa.or_(sa.func.lower(name).like(like), sa.func.lower(members.c.email).like(like)))
        async with self.db.tenant_tx(tenant_id) as c:
            rows = (await c.execute(q.offset(offset).limit(limit))).all()
        return [{"id": r[0], "label": r[1], "hint": r[0] if r[1] != r[0] else None} for r in rows]

    async def invite(
        self, actor: Actor, *, invites: dict[str, str], role: str, expires_at: str, at: str
    ) -> tuple[Bulk, list[dict[str, str]]]:
        """`invites` maps each lower-cased email to its token hash. Returns the bulk result and, per new invite, its
        member id and email; the caller pairs those with the plain tokens it kept."""
        bulk, made = Bulk(), list[dict[str, str]]()
        async with self.db.tenant_tx(actor.tenant_id) as c:
            status = (await c.execute(sa.select(teams.c.status).where(teams.c.id == actor.team_id))).scalar()
            if status != "active":
                raise TeamArchivedError
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
                if row["status"] == "active" and row["user_id"] is not None:
                    await self._mirror(c, actor, str(row["user_id"]), role, at)
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
                    await self._mirror(c, actor, str(user_id), None, at)
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

    async def account_of(self, invite: Invite) -> str | None:
        """The id of the tenant's person who already has the invited email, if any."""
        q = sa.select(users.c.id).where(sa.func.lower(users.c.email) == invite.email.lower())
        async with self.db.tenant_tx(invite.tenant_id) as c:
            return (await c.execute(q)).scalar()

    async def inviter(self, invite: Invite) -> str | None:
        """The name of the person who sent the invite, from its audit entry; None when that entry names nobody."""
        q = (
            sa.select(sa.func.coalesce(users.c.name, users.c.email))
            .select_from(audit_entries.join(users, users.c.id == audit_entries.c.actor))
            .where(audit_entries.c.action == "member.invite", audit_entries.c.target_id == invite.member_id)
            .order_by(audit_entries.c.at.desc())
            .limit(1)
        )
        async with self.db.tenant_tx(invite.tenant_id) as c:
            return (await c.execute(q)).scalar()

    async def accept(self, invite: Invite, *, name: str, caller: str | None, at: str, request_id: str) -> str | None:
        """Makes the invited member active for `caller` (a verified session's user id) or, when the email has no
        account, for a new user made from the invite. Returns the user id, or None when the invite was accepted or
        withdrawn meanwhile. Raises `NotTheInvitee` when the email has an account that is not the caller's. Both
        checks are conditions inside the one transaction, never a read before it: an account made after an earlier
        check is found here, or refuses the insert through `uq_users_tenant_email`, so the link never opens it."""
        try:
            return await self._accept(invite, name=name, caller=caller, at=at, request_id=request_id)
        except _AlreadyDone:
            return None
        except IntegrityError as e:
            # Another accept made this email's account between our read and our insert.
            raise NotTheInvitee(signed_in=caller is not None) from e

    async def _accept(self, invite: Invite, *, name: str, caller: str | None, at: str, request_id: str) -> str:
        async with self.db.tenant_tx(invite.tenant_id) as c:
            user_id = (
                await c.execute(sa.select(users.c.id).where(sa.func.lower(users.c.email) == invite.email.lower()))
            ).scalar()
            if user_id is not None and user_id != caller:
                raise NotTheInvitee(signed_in=caller is not None)
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
            await self._mirror(c, actor, user_id, invite.role, at)
            await _audit(c, actor, "member.accept", invite.member_id, {"email": invite.email})
        return user_id


class TeamArchivedError(Exception):
    """The team is archived and takes no new members (c-198)."""


class NotTheInvitee(Exception):
    """The invited email has an account, and the accept is not signed in as it."""

    def __init__(self, *, signed_in: bool) -> None:
        super().__init__("not the invitee")
        self.signed_in = signed_in


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
