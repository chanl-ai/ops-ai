"""The workspace's access policies as the API serves them: every policy in the catalogue with its value, its
open default, the grid cell a change needs and its effect. Every member reads them; a change goes through `can()` on
the policy's cell, in the team the request acts in, as the sign-in settings do."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, NotRequired, TypedDict

from ops_access import BY_KEY, POLICIES
from ops_service_kit import narrow
from ops_service_kit.errors import Conflict, Unprocessable, ValidationFailed
from ops_service_kit.http import Json, JsonValue

from .store.members import Actor
from .store.policies import OLD_KEYS, BelowFloorError, PolicyStore
from .store.roles import RoleStore
from .teams import Members

Guard = Callable[[Actor, Any], Awaitable[None]]


class PolicyChoiceView(TypedDict):
    value: str
    title: str
    description: str


class PolicyView(TypedDict):
    """One policy as `PolicyOut` sends it."""

    key: str
    value: JsonValue
    # The catalogue's open default, any JSON value.
    default: Any
    changedBy: str
    effect: str
    kind: str
    title: str
    choices: NotRequired[list[PolicyChoiceView]]
    note: NotRequired[str]


@dataclass
class Policies:
    store: PolicyStore
    members: Members
    # Checks a value must pass before it is set, by policy key (companySignInRequired needs a break-glass account).
    guards: dict[str, Guard] = field(default_factory=dict[str, "Guard"])

    async def list(self, actor: Actor) -> list[PolicyView]:
        """Every member of the workspace reads every policy: they are not secret, and a person who may change one
        must see it. Changing stays on each policy's cell."""
        return await self.for_tenant(actor.tenant_id)

    async def for_tenant(self, tenant_id: str) -> list[PolicyView]:
        """Every policy of the tenant, for a service whose token holds `settings:view` (a background sweep has no
        person, so no token carrying the values)."""
        return self._rows(await self.store.values(tenant_id))

    async def set(self, actor: Actor, key: str, value: Any) -> PolicyView:
        if key == "requesterMayDecide":
            # Approve own requests is the Approvals · decide cell from 1.2.0; the stored value stays, false, for a
            # rolled-back service to read, and an older console that saves it is told where the setting went.
            raise Conflict(
                "Who may approve their own requests is now the Approvals · decide row of the roles matrix.",
                code="policy_retired",
                details={"area": "approvals", "action": "decide"},
            )
        # The cell the policy names: settings.manage in the security team for most, approvals.manage in the acting team
        # for a team's approval rule (`held_in`), chat.manage for memory retention.
        # An old key lands in appChanges / appChangesByApp (the store moves it), so the cell checked is that key's:
        # otherwise a holder of the old key's cell could change what its cell never covered.
        landing = {"toolWritesNeedApproval": "appChanges"}.get(key, "appChangesByApp") if key in OLD_KEYS else key
        policy = BY_KEY.get(landing)
        area, action = policy.changed_by if policy else ("settings", "manage")
        await self.members.require_admin(actor, area, action, in_team=bool(policy and policy.held_in == "team"))
        if policy and policy.maximum and type(value) is int and value > policy.maximum:
            raise Unprocessable(f"{policy.title} is at most {policy.maximum} hours.", code="policy_value")
        await self._check_reviewer_roles(actor, key, value)
        if (guard := self.guards.get(key)) is not None:
            await guard(actor, value)
        try:
            await self.store.set(
                actor.tenant_id, key, value, by=actor.user_id, request_id=actor.request_id, team_id=actor.team_id
            )
        except BelowFloorError as e:
            # The Security team's floor (approvalsFloor, row E55): a team's approval rule may be stricter, never looser.
            raise Conflict(str(e), code="approval_floor") from e
        except ValueError as e:
            raise ValidationFailed(str(e), code="policy_value") from e
        return next(r for r in self._rows(await self.store.values(actor.tenant_id)) if r["key"] == key)

    async def _check_reviewer_roles(self, actor: Actor, key: str, value: Any) -> None:
        """A "reviewer" answer names a role, and the role must be able to decide reviews: otherwise nobody could ever
        answer and every change would wait for good. A role that does not exist is refused for the same reason."""
        # Read only when it is an object, as the isinstance checks say; `json_object` is the same object then.
        given = narrow.json_object(value)
        entries: list[Json] = []
        if key == "appChanges" and isinstance(value, dict) and given.get("ask"):
            entries = [given]
        elif key == "appChangesByApp" and isinstance(value, dict):
            entries = [narrow.json_object(e) for e in given.values() if isinstance(e, dict)]
        else:
            return
        roles = self.members.roles or RoleStore(self.members.store)
        for entry in entries:
            if entry.get("answer") != "reviewer":
                continue
            role_id = entry.get("reviewerRole")
            if not role_id:
                raise ValidationFailed("Choose the role that reviews.", code="reviewer_role_required")
            role = await roles.role_by_id(actor.tenant_id, str(role_id))
            if role is None:
                raise ValidationFailed(
                    f"There is no role {role_id}. Choose a role that can approve.", code="reviewer_role_unknown"
                )
            if not any(g[:2] == ("reviews", "decide") for g in role.grants):
                raise ValidationFailed(
                    f"{role.name} cannot decide reviews. Choose a role that can approve.", code="role_cannot_approve"
                )

    @staticmethod
    def _rows(values: Json) -> list[PolicyView]:
        rows: list[PolicyView] = []
        for p in POLICIES:
            row: PolicyView = {
                "key": p.key,
                "value": values[p.key],
                "default": p.default,
                "changedBy": ".".join(p.changed_by),
                "effect": p.effect,
                # How the Policies page draws it and names it, so a new policy needs no console change.
                "kind": p.kind,
                "title": p.title,
            }
            if p.choices:
                row["choices"] = [{"value": v, "title": t, "description": d} for v, t, d in p.choices]
            if p.note:
                row["note"] = p.note
            rows.append(row)
        return rows
