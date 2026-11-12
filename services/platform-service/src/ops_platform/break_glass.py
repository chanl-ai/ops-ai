"""Break-glass password accounts (decision D7): while a workspace's `companySignInRequired` policy is on, a person on
a verified SSO domain signs in only through the company's provider, except the named Security admins on this list, who
may always use a password, so the workspace can still be reached when the provider is down.

A person counts only while they hold `settings.manage` in the Security team: losing the role takes them off the list
at once, whatever the table holds. At most three people; while company sign-in is required the last one cannot be
removed, and the policy cannot turn on with nobody on the list. Each password sign-in by one of them is audited and
told to the Security admins. The usual lockout applies to them (`passwords.py`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ops_service_kit.errors import Conflict, NotFound, Unprocessable

from .store.holders import HolderStore
from .store.identity import User
from .store.members import Actor
from .store.policies import PolicyStore
from .store.signin import SignInStore
from .store.workspace import WorkspaceStore
from .teams import Members

REQUIRED = "companySignInRequired"
MOST = 3

# Tells the workspace's Security admins: (tenant id, target, subject, body).
Notify = Callable[[str, str, str, str], Awaitable[None]]


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class BreakGlass:
    store: SignInStore
    holders: HolderStore
    workspace: WorkspaceStore
    policies: PolicyStore
    members: Members
    notify: Notify | None = None

    async def required(self, tenant_id: str) -> bool:
        return (await self.policies.values(tenant_id)).get(REQUIRED) is True

    async def _security_admins(self, tenant_id: str) -> set[str]:
        team = await self.workspace.security_team(tenant_id)
        found: dict[str, Any] = await self.holders.holders(tenant_id, team, "settings", "manage") if team else {}
        return {str(p["id"]) for p in found.get("holders", [])}

    async def people(self, tenant_id: str) -> list[dict[str, Any]]:
        """The people on the list who still count."""
        admins = await self._security_admins(tenant_id)
        return [p for p in await self.store.break_glass(tenant_id) if p["userId"] in admins]

    async def counts(self, user: User) -> bool:
        return any(p["userId"] == user.id for p in await self.people(user.tenant_id))

    async def list(self, actor: Actor) -> list[dict[str, Any]]:
        await self.members.require_admin(actor, "settings", "view")
        return await self.people(actor.tenant_id)

    async def add(self, actor: Actor, user_id: str) -> list[dict[str, Any]]:
        await self.members.require_admin(actor, "settings", "manage")
        if user_id not in await self._security_admins(actor.tenant_id):
            raise Unprocessable(
                "Only a Security admin can be a break-glass account.", code="break_glass_not_security_admin"
            )
        now = await self.people(actor.tenant_id)
        if user_id not in {p["userId"] for p in now} and len(now) >= MOST:
            raise Unprocessable(f"At most {MOST} people can be break-glass accounts.", code="break_glass_full")
        await self.store.add_break_glass(
            actor.tenant_id, user_id, actor=actor.user_id, at=_iso(datetime.now(UTC)), request_id=actor.request_id
        )
        return await self.people(actor.tenant_id)

    async def remove(self, actor: Actor, user_id: str) -> list[dict[str, Any]]:
        await self.members.require_admin(actor, "settings", "manage")
        now = await self.people(actor.tenant_id)
        if [p["userId"] for p in now] == [user_id] and await self.required(actor.tenant_id):
            raise Conflict(
                "Company sign-in is required, so one break-glass account must stay. Add another first, or turn "
                "company sign-in required off.",
                code="break_glass_last",
            )
        if not await self.store.remove_break_glass(
            actor.tenant_id, user_id, actor=actor.user_id, request_id=actor.request_id
        ):
            raise NotFound("break-glass account")
        return await self.people(actor.tenant_id)

    async def guard_policy(self, actor: Actor, value: Any) -> None:
        """Company sign-in cannot be required before someone can still get in when the provider is down."""
        if value is True and not await self.people(actor.tenant_id):
            raise Conflict("Add a break-glass account before requiring company sign-in.", code="break_glass_none")

    async def guard_last_provider(self, tenant_id: str) -> None:
        """Turning off or deleting a company provider whose verified domains route people, while company sign-in is
        required and no break-glass account counts, would leave those people no way in."""
        if await self.required(tenant_id) and not await self.people(tenant_id):
            raise Conflict(
                "Company sign-in is required and nobody has a break-glass account, so this provider is the only way "
                "in for its domains. Add a break-glass account first.",
                code="last_sign_in_method",
            )

    async def used(self, user: User, *, request_id: str) -> None:
        await self.store.break_glass_used(user.tenant_id, user.id, at=_iso(datetime.now(UTC)), request_id=request_id)
        if self.notify is not None:
            await self.notify(
                user.tenant_id,
                user.id,
                "A break-glass account signed in with a password",
                f"{user.email} signed in to Ops AI with a password, as a break-glass account. If this was not "
                "planned, check the account and your company sign-in.",
            )
