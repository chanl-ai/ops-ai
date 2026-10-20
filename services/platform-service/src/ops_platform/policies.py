"""The workspace's access policies as the API serves them (c-186): every policy in the catalogue with its value, its
open default, the grid cell a change needs and its effect. Every member reads them; a change goes through `can()` on
the policy's cell, in the team the request acts in, as the sign-in settings do."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ops_access import BY_KEY, POLICIES
from ops_service_kit.errors import ValidationFailed

from .store.members import Actor
from .store.policies import PolicyStore
from .teams import Members


@dataclass
class Policies:
    store: PolicyStore
    members: Members

    async def list(self, actor: Actor) -> list[dict[str, Any]]:
        """Every member of the workspace reads every policy: they are not secret, and a person who may change one
        must see it (owner, 2026-10-18). Changing stays on each policy's cell."""
        return await self.for_tenant(actor.tenant_id)

    async def for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        """Every policy of the tenant, for a service whose token holds `settings:view` (a background sweep has no
        person, so no token carrying the values)."""
        return self._rows(await self.store.values(tenant_id))

    async def set(self, actor: Actor, key: str, value: Any) -> dict[str, Any]:
        # The cell the policy names: settings.manage in the security team for most, chat.manage for memory retention.
        policy = BY_KEY.get(key)
        area, action = policy.changed_by if policy else ("settings", "manage")
        await self.members.require_admin(actor, area, action)
        try:
            await self.store.set(
                actor.tenant_id, key, value, by=actor.user_id, request_id=actor.request_id, team_id=actor.team_id
            )
        except ValueError as e:
            raise ValidationFailed(str(e), code="policy_value") from e
        return next(r for r in self._rows(await self.store.values(actor.tenant_id)) if r["key"] == key)

    @staticmethod
    def _rows(values: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "key": p.key,
                "value": values[p.key],
                "default": p.default,
                "changedBy": ".".join(p.changed_by),
                "effect": p.effect,
                # How the Policies page draws it and names it (c-224), so a new policy needs no console change.
                "kind": p.kind,
                "title": p.title,
            }
            for p in POLICIES
        ]
