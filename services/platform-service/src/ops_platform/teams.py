"""Members and invites: the decisions, with storage behind `TeamStore`.

The caller's role is read from the database on each write, not from the token, so a demoted admin loses the right
at once rather than when their token expires. An invite token is `inv_<random>`, shown once in the invite response
for the admin to share (no mail is sent in this slice) and stored only as its hash. An invite lasts 7 days.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ops_access import Access, Grids, active
from ops_identity import Principal
from ops_service_kit.errors import Conflict, Forbidden, NotFound, Unauthorized
from ops_service_kit.ids import now_iso

from .store.members import Actor, Bulk, Invite, NotTheInvitee, TeamArchivedError, TeamStore
from .store.roles import RoleStore

INVITE_TTL = timedelta(days=7)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _bulk(b: Bulk) -> dict[str, Any]:
    return {"updated": b.updated, "skipped": b.skipped}


@dataclass
class Members:
    store: TeamStore
    # Where a caller's role assignments are read for `require_admin`; the tenant's RoleStore unless a test gives one.
    roles: RoleStore | None = None

    async def require_admin(self, actor: Actor, area: str = "access", action: str = "manage") -> None:
        """`can(area, action)` in the actor's team, from the roles the database holds now rather than the token's, so a
        demoted admin loses the right at once (c-149). The refusal keeps its documented code, `admin_required`."""
        roles = self.roles or RoleStore(self.store.db)
        held = await roles.holdings(actor.tenant_id, actor.user_id)
        live = active(held.assignments, now_iso())
        version = await roles.version(actor.tenant_id)
        p = Principal(
            kind="person",
            sub=actor.user_id,
            email="",
            name="",
            roles={},
            scopes=[],
            tenant_id=actor.tenant_id,
            team_id=actor.team_id,
            team_ids=list(held.teams),
            access={t: [a.role_id for a in live if a.team_id == t] for t in {a.team_id for a in live}},
            permission_version=version,
            auth_method="session",
        )
        access = Access(
            security_team=await self.store.security_team_of(actor.tenant_id),
            grids=Grids(fetch=lambda t, _v, ids: roles.grids(t, ids)),
        )
        await access.grids.load(actor.tenant_id, version, [a.role_id for a in live])
        access.can(p, area, action, team=actor.team_id, what="this team", code="admin_required")

    async def invite(self, actor: Actor, emails: list[str], role: str) -> dict[str, Any]:
        await self.require_admin(actor, "access", "create")
        now = datetime.now(UTC)
        tokens = {e.strip().lower(): f"inv_{secrets.token_urlsafe(24)}" for e in emails}
        try:
            bulk, made = await self.store.invite(
                actor,
                invites={email: _hash(token) for email, token in tokens.items()},
                role=role,
                expires_at=_iso(now + INVITE_TTL),
                at=_iso(now),
            )
        except TeamArchivedError as e:
            raise Conflict("This team is archived and takes no new members.", code="team_archived") from e
        invites = [{**m, "token": tokens[m["email"]]} for m in made]
        return {**_bulk(bulk), "invites": invites}

    async def set_role(self, actor: Actor, ids: list[str], role: str) -> dict[str, Any]:
        await self.require_admin(actor, "access", "edit")
        return _bulk(await self.store.set_role(actor, ids, role, at=_iso(datetime.now(UTC))))

    async def remove(self, actor: Actor, ids: list[str]) -> dict[str, Any]:
        await self.require_admin(actor, "access", "delete")
        return _bulk(await self.store.remove(actor, ids, at=_iso(datetime.now(UTC))))

    async def find(self, token: str) -> Invite:
        invite = await self.store.invite_by_hash(_hash(token))
        if invite is None or invite.status == "removed":
            raise NotFound("No invitation matches this link.")
        return invite

    async def preview(self, token: str) -> dict[str, Any]:
        invite = await self.find(token)
        return {
            "token": token,
            "email": invite.email,
            "teamId": invite.team_id,
            "team": invite.team,
            "role": invite.role,
            "invitedBy": await self.store.inviter(invite),
            "existingAccount": await self.store.account_of(invite) is not None,
            "invitedAt": invite.invited_at,
            "expiresAt": invite.expires_at,
            "state": state_of(invite, _iso(datetime.now(UTC))),
        }

    async def accept(self, token: str, name: str, *, caller: str | None, request_id: str) -> tuple[Invite, str]:
        """Accepts for `caller`, the user id of a verified session, or None. An invitation to an email that already
        has an account is accepted only by that person signed in as themselves: the link alone never opens their
        account, or anyone holding it would act as them in every team they belong to. Only a new person is
        created and signed in from the link."""
        invite = await self.find(token)
        now = _iso(datetime.now(UTC))
        state = state_of(invite, now)
        if state == "accepted":
            raise Conflict("This invitation has been used.", code="invite_used")
        if state == "expired":
            raise Conflict("This invitation has expired; ask an admin for a new one.", code="invite_expired")
        domain = invite.email.rsplit("@", 1)[-1].lower()
        if invite.allowed_domains and domain not in {d.lower() for d in invite.allowed_domains}:
            raise Forbidden(
                "This organisation does not accept members from that email domain.", code="domain_not_allowed"
            )
        # Refused inside the accept's transaction, so an account made after any earlier read is still found.
        try:
            user_id = await self.store.accept(invite, name=name, caller=caller, at=now, request_id=request_id)
        except NotTheInvitee as e:
            if e.signed_in:
                message = f"This invitation is for {invite.email}; sign in as them to accept it."
                raise Forbidden(message, code="not_the_invitee") from e
            message = f"{invite.email} already has an account; sign in as them to accept."
            raise Unauthorized(message, code="sign_in_as_invitee") from e
        if user_id is None:
            raise Conflict("This invitation has been used.", code="invite_used")
        return invite, user_id


def state_of(invite: Invite, now: str) -> str:
    if invite.status == "active":
        return "accepted"
    return "expired" if invite.expires_at <= now else "pending"
