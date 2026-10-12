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

from ops_service_kit.errors import Conflict, Forbidden, NotFound

from .store.members import Actor, Bulk, Invite, TeamStore

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

    async def require_admin(self, actor: Actor) -> None:
        if await self.store.role_in(actor.tenant_id, actor.team_id, actor.user_id) != "admin":
            raise Forbidden("Only a team admin can do this.", code="admin_required")

    async def invite(self, actor: Actor, emails: list[str], role: str) -> dict[str, Any]:
        await self.require_admin(actor)
        now = datetime.now(UTC)
        tokens = {e.strip().lower(): f"inv_{secrets.token_urlsafe(24)}" for e in emails}
        bulk, made = await self.store.invite(
            actor,
            invites={email: _hash(token) for email, token in tokens.items()},
            role=role,
            expires_at=_iso(now + INVITE_TTL),
            at=_iso(now),
        )
        invites = [{**m, "token": tokens[m["email"]]} for m in made]
        return {**_bulk(bulk), "invites": invites}

    async def set_role(self, actor: Actor, ids: list[str], role: str) -> dict[str, Any]:
        await self.require_admin(actor)
        return _bulk(await self.store.set_role(actor, ids, role, at=_iso(datetime.now(UTC))))

    async def remove(self, actor: Actor, ids: list[str]) -> dict[str, Any]:
        await self.require_admin(actor)
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
            "invitedAt": invite.invited_at,
            "expiresAt": invite.expires_at,
            "state": state_of(invite, _iso(datetime.now(UTC))),
        }

    async def accept(self, token: str, name: str, *, request_id: str) -> tuple[Invite, str]:
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
        user_id = await self.store.accept(invite, name=name, at=now, request_id=request_id)
        if user_id is None:
            raise Conflict("This invitation has been used.", code="invite_used")
        return invite, user_id


def state_of(invite: Invite, now: str) -> str:
    if invite.status == "active":
        return "accepted"
    return "expired" if invite.expires_at <= now else "pending"
