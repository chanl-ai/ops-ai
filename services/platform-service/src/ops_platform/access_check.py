"""Check one action for one person (c-150): the same `can()` the services run, for that person's roles now and the
workspace's policies, answering allowed with the scope and the roles that grant it, or refused with the reason. The
admin who asks needs `access.view` in the team; every check is written to the audit log."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ops_access import Access, Grids, active, effective
from ops_identity import Principal
from ops_service_kit.errors import Forbidden, NotFound
from ops_service_kit.ids import now_iso

from .store.holders import HolderStore
from .store.identity import IdentityStore
from .store.members import Actor, TeamStore
from .store.policies import PolicyStore
from .store.roles import RoleStore
from .teams import Members


@dataclass
class AccessCheck:
    roles: RoleStore
    teams: TeamStore
    identity: IdentityStore
    policies: PolicyStore
    members: Members
    holders: HolderStore

    async def check(
        self,
        caller: Actor,
        person_id: str,
        area: str,
        action: str,
        *,
        owner: str | None = None,
        requested_by: str | None = None,
    ) -> dict[str, Any]:
        """`caller.team_id` is the team the check is for; the caller must be able to view access there."""
        await self.members.require_admin(caller, "access", "view")
        answer = await self._answer(
            caller.tenant_id,
            caller.team_id,
            person_id,
            area,
            action,
            owner=owner,
            requested_by=requested_by,
            about_someone_else=person_id != caller.user_id,
        )
        await self.roles.record_check(
            caller.tenant_id,
            caller.team_id,
            by=caller.user_id,
            request_id=caller.request_id,
            detail=answer | {"owner": owner, "requestedBy": requested_by},
        )
        return answer

    async def why(self, caller: Actor, area: str, action: str) -> dict[str, Any]:
        """The caller's own answer for `area.action` in the team they act in, the roles that grant it there, and who
        in the team can give roles: what a locked button says. Not audited, as a person reads only their own."""
        answer = await self._answer(
            caller.tenant_id, caller.team_id, caller.user_id, area, action, owner=None, requested_by=None
        )
        granting = await self.holders.holders(caller.tenant_id, caller.team_id, area, action)
        admins = await self.holders.holders(caller.tenant_id, caller.team_id, "access", "manage")
        return answer | {"roles": granting["roles"], "askable": [h["name"] for h in admins["holders"]]}

    async def _answer(
        self,
        tenant: str,
        team: str,
        person_id: str,
        area: str,
        action: str,
        *,
        owner: str | None,
        requested_by: str | None,
        about_someone_else: bool = False,
    ) -> dict[str, Any]:
        who = await self.identity.user(tenant, person_id)
        if who is None:
            raise NotFound("No person with that id.")
        held = await self.roles.holdings(tenant, person_id)
        now = now_iso()
        live = active(held.assignments, now)
        version = await self.roles.version(tenant)
        p = Principal(
            kind="person",
            sub=person_id,
            email=who.email,
            name=who.name,
            roles={},
            scopes=[],
            tenant_id=tenant,
            team_id=team,
            team_ids=list(held.teams),
            access={t: [a.role_id for a in live if a.team_id == t] for t in {a.team_id for a in live}},
            permission_version=version,
            auth_method="session",
            policies=await self.policies.token_values(tenant),
        )
        access = Access(
            security_team=await self.teams.security_team_of(tenant),
            grids=Grids(fetch=lambda t, _v, ids: self.roles.grids(t, ids)),
        )
        await access.grids.load(tenant, version, [a.role_id for a in live])
        answer: dict[str, Any] = {"personId": person_id, "teamId": team, "area": area, "action": action}
        try:
            # An admin checking someone reads a refusal about that person, not one addressed to themselves.
            scope = access.can(
                p,
                area,
                action,
                team=team,
                owner=owner,
                requested_by=[requested_by],
                what="this",
                speaking_of=(who.name or who.email) if about_someone_else else None,
            )
            grids = await self.roles.grids(tenant, sorted({a.role_id for a in live}))
            granted = effective(live, grids, [team], now).get(team, {}).get((area, action))
            answer |= {
                "allowed": True,
                "scope": scope,
                "grantedBy": list(granted.roles) if granted else [],
                "refusedBy": None,
            }
        except Forbidden as e:
            answer |= {
                "allowed": False,
                "scope": None,
                "grantedBy": [],
                "refusedBy": {"code": e.code, "reason": e.message},
            }
        return answer
