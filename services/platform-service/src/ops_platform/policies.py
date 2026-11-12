"""The workspace's access policies as the API serves them: every policy in the catalogue with its value, its
open default, the grid cell a change needs and its effect. Every member reads them; a change goes through `can()` on
the policy's cell, in the team the request acts in, as the sign-in settings do."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

from ops_access import BY_KEY, POLICIES
from ops_service_kit.errors import ValidationFailed

from .store.members import Actor
from .store.policies import OLD_KEYS, PolicyStore
from .store.roles import RoleStore
from .teams import Members

Guard = Callable[[Actor, Any], Awaitable[None]]


@dataclass
class Policies:
    store: PolicyStore
    members: Members
    # Checks a value must pass before it is set, by policy key (companySignInRequired needs a break-glass account).
    guards: dict[str, Guard] = field(default_factory=dict[str, "Guard"])

    async def list(self, actor: Actor) -> list[dict[str, Any]]:
        """Every member of the workspace reads every policy: they are not secret, and a person who may change one
        must see it. Changing stays on each policy's cell."""
        return await self.for_tenant(actor.tenant_id)

    async def for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        """Every policy of the tenant, for a service whose token holds `settings:view` (a background sweep has no
        person, so no token carrying the values)."""
        return self._rows(await self.store.values(tenant_id))

    async def set(self, actor: Actor, key: str, value: Any) -> dict[str, Any]:
        # The cell the policy names: settings.manage in the security team for most, chat.manage for memory retention.
        # An old key lands in appChanges / appChangesByApp (the store moves it), so the cell checked is that key's:
        # otherwise a holder of the old key's cell could change what its cell never covered.
        landing = {"toolWritesNeedApproval": "appChanges"}.get(key, "appChangesByApp") if key in OLD_KEYS else key
        policy = BY_KEY.get(landing)
        area, action = policy.changed_by if policy else ("settings", "manage")
        await self.members.require_admin(actor, area, action)
        await self._check_reviewer_roles(actor, key, value)
        if (guard := self.guards.get(key)) is not None:
            await guard(actor, value)
        try:
            await self.store.set(
                actor.tenant_id, key, value, by=actor.user_id, request_id=actor.request_id, team_id=actor.team_id
            )
        except ValueError as e:
            raise ValidationFailed(str(e), code="policy_value") from e
        return next(r for r in self._rows(await self.store.values(actor.tenant_id)) if r["key"] == key)

    async def _check_reviewer_roles(self, actor: Actor, key: str, value: Any) -> None:
        """A "reviewer" answer names a role, and the role must be able to decide reviews: otherwise nobody could ever
        answer and every change would wait for good. A role that does not exist is refused for the same reason."""
        entries: list[dict[str, Any]] = []
        if key == "appChanges" and isinstance(value, dict) and cast(dict[str, Any], value).get("ask"):
            entries = [cast(dict[str, Any], value)]
        elif key == "appChangesByApp" and isinstance(value, dict):
            entries = [cast(dict[str, Any], e) for e in cast(dict[str, Any], value).values() if isinstance(e, dict)]
        else:
            return
        roles = self.members.roles or RoleStore(self.members.store.db)
        for entry in entries:
            if entry.get("answer") != "reviewer":
                continue
            role_id = entry.get("reviewerRole")
            if not role_id:
                raise ValidationFailed("Choose the role that reviews.", code="reviewer_role_required")
            role = await roles.role(actor.tenant_id, str(role_id))
            if role is None:
                raise ValidationFailed(
                    f"There is no role {role_id}. Choose a role that can approve.", code="reviewer_role_unknown"
                )
            if not any(g[:2] == ("reviews", "decide") for g in role["grants"]):
                raise ValidationFailed(
                    f"{role['name']} cannot decide reviews. Choose a role that can approve.", code="role_cannot_approve"
                )

    @staticmethod
    def _rows(values: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "key": p.key,
                "value": values[p.key],
                "default": p.default,
                "changedBy": ".".join(p.changed_by),
                "effect": p.effect,
                # How the Policies page draws it and names it, so a new policy needs no console change.
                "kind": p.kind,
                "title": p.title,
                **(
                    {"choices": [{"value": v, "title": t, "description": d} for v, t, d in p.choices]}
                    if p.choices
                    else {}
                ),
                **({"note": p.note} if p.note else {}),
            }
            for p in POLICIES
        ]
