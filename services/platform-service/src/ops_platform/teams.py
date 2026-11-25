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
from typing import TypedDict

from ops_email import MailSender, OutboundMessage
from ops_service_kit.errors import Conflict, Forbidden, NotFound, ServiceUnavailable, Unauthorized

from .store.members import Actor, Bulk, Invite, NotTheInvitee, TeamArchivedError, TeamStore
from .store.roles import RoleStore
from .store.signin import SignInStore

INVITE_TTL = timedelta(days=7)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class BulkView(TypedDict):
    updated: list[str]
    skipped: list[dict[str, str]]


class InvitedView(BulkView):
    """The invites made, each with its token, shown once."""

    invites: list[dict[str, str]]


class ReinvitedView(BulkView):
    """The link invites mailed: to whom, never their tokens."""

    mailed: list[dict[str, str]]


class InvitePreviewView(TypedDict):
    token: str
    email: str
    teamId: str
    team: str
    role: str
    invitedBy: str | None
    existingAccount: bool
    invitedAt: str
    expiresAt: str
    state: str


def _bulk(b: Bulk) -> BulkView:
    return {"updated": b.updated, "skipped": b.skipped}


@dataclass
class Members:
    store: TeamStore
    # Where a caller's role assignments are read for `require_admin`; the tenant's RoleStore unless a test gives one.
    roles: RoleStore | None = None
    # Where link invites are mailed and the console address they open; unset, a reinvite is refused.
    mail: MailSender | None = None
    console_url: str | None = None
    # The provider links an admin removes; unset, the unlink route is refused.
    signin: SignInStore | None = None

    async def require_admin(
        self, actor: Actor, area: str = "access", action: str = "manage", *, in_team: bool = False
    ) -> None:
        """`can(area, action)` in the actor's team, from the roles the database holds now rather than the token's, so a
        demoted admin loses the right at once. The refusal keeps its documented code, `admin_required`."""
        roles = self.roles or RoleStore(self.store)
        p, access = await roles.live(actor.tenant_id, actor.user_id, team=actor.team_id)
        access.can(p, area, action, team=actor.team_id, what="this team", code="admin_required", in_team=in_team)

    async def invite(self, actor: Actor, emails: list[str], role: str) -> InvitedView:
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
        done = _bulk(bulk)
        return {"updated": done["updated"], "skipped": done["skipped"], "invites": invites}

    async def reinvite(self, actor: Actor, ids: list[str] | None) -> ReinvitedView:
        """A link invite for each active member who has no provider link and no password in a workspace that signs in
        only through a provider; the member stays active, and an SSO sign-in from the invite links their person and
        changes no role. The link is mailed to the member's own address only and never returned: holding it is the
        proof that the mailbox is theirs. Single use, for `INVITE_TTL`."""
        await self.require_admin(actor, "access", "create")
        if self.mail is None or self.console_url is None:
            raise ServiceUnavailable("Invites cannot be mailed on this installation.", code="mail_not_configured")
        now = datetime.now(UTC)
        wanted = ids if ids is not None else await self.store.affected(actor.tenant_id, actor.team_id)
        tokens = {m: f"inv_{secrets.token_urlsafe(24)}" for m in wanted}
        bulk, made = await self.store.reinvite(
            actor,
            ids,
            tokens={m: _hash(t) for m, t in tokens.items()},
            expires_at=_iso(now + INVITE_TTL),
            at=_iso(now),
        )
        console = self.console_url.rstrip("/")
        for m in made:
            token = tokens[m["memberId"]]
            body = (
                f"Your workspace admin asked you to sign in to Ops AI with your company account.\n\n"
                f"Sign in: {console}/invite/{token}\n\n"
                f"The link works once, for {INVITE_TTL.days} days, and only for {m['email']}."
            )
            await self.mail.send(
                OutboundMessage(
                    key=f"link-invite:{_hash(token)}", to=(m["email"],), subject="Sign in with your company", body=body
                )
            )
        done = _bulk(bulk)
        return {"updated": done["updated"], "skipped": done["skipped"], "mailed": made}

    async def unlink(self, actor: Actor, ids: list[str]) -> BulkView:
        """Removes the provider links of each member's person, and ends the sessions they made, audited; a member with
        none is skipped `not_linked`. For an account taken over at the provider, or a person who must link again."""
        await self.require_admin(actor, "access", "edit")
        if self.signin is None:
            raise ServiceUnavailable("Sign-in links cannot be changed here.", code="sso_not_configured")
        bulk = Bulk()
        people = await self.store.people_of(actor.tenant_id, actor.team_id, ids)
        at = _iso(datetime.now(UTC))
        for member_id in ids:
            user_id = people.get(member_id)
            if user_id is None:
                bulk.skip(member_id, "not_found")
                continue
            gone = await self.signin.unlink(
                actor.tenant_id, user_id, actor=actor.user_id, team_id=actor.team_id, at=at, request_id=actor.request_id
            )
            if gone:
                bulk.updated.append(member_id)
            else:
                bulk.skip(member_id, "not_linked")
        return _bulk(bulk)

    async def set_role(self, actor: Actor, ids: list[str], role: str) -> BulkView:
        await self.require_admin(actor, "access", "edit")
        return _bulk(await self.store.set_role(actor, ids, role, at=_iso(datetime.now(UTC))))

    async def remove(self, actor: Actor, ids: list[str]) -> BulkView:
        await self.require_admin(actor, "access", "delete")
        return _bulk(await self.store.remove(actor, ids, at=_iso(datetime.now(UTC))))

    async def find(self, token: str) -> Invite:
        invite = await self.store.invite_by_hash(_hash(token))
        if invite is None or invite.status == "removed":
            raise NotFound("No invitation matches this link.")
        return invite

    async def preview(self, token: str) -> InvitePreviewView:
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
    # An active member with an expiry has a pending new invite (`TeamStore.reinvite`); without one it was accepted.
    if invite.status == "active" and not invite.expires_at:
        return "accepted"
    return "expired" if invite.expires_at <= now else "pending"
