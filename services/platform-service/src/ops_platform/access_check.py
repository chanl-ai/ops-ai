"""Check one action for one person: the same `can()` the services run, for that person's roles now and the
workspace's policies, answering allowed with the scope and the roles that grant it, or refused with the reason. The
admin who asks needs `access.view` in the team; every check is written to the audit log."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NotRequired, TypedDict

from ops_access import BUILTIN_ROLES, Access, Grids, Scope, active, effective
from ops_identity import Principal
from ops_service_kit import narrow
from ops_service_kit.errors import Forbidden, NotFound
from ops_service_kit.ids import now_iso

from .store.holders import HolderStore
from .store.identity import IdentityStore, User
from .store.members import Actor, TeamStore
from .store.policies import PolicyStore
from .store.roles import RoleStore
from .teams import Members


class Refusal(TypedDict):
    code: str
    reason: str


class GrantingRoleReply(TypedDict):
    id: str
    name: str


class AccessAnswer(TypedDict):
    """One check's answer, sent as it is and written to the audit log; keys in the order they are sent."""

    personId: str
    teamId: str
    area: str
    action: str
    allowed: bool
    scope: Scope | None
    # Each role that grants the cell, as the grid names it.
    grantedBy: list[dict[str, str]]
    refusedBy: Refusal | None
    # The caller's own answer only (`why`): the roles granting it in the team, and who there can give roles.
    roles: NotRequired[list[GrantingRoleReply]]
    askable: NotRequired[list[str]]


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
    ) -> AccessAnswer:
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
            # The answer as sent, then what was asked about; a TypedDict is not a Mapping of JSON to the checker.
            detail=narrow.an_object(answer | {"owner": owner, "requestedBy": requested_by}, "the access check"),
        )
        return answer

    async def for_service(
        self, tenant: str, team: str, email: str, area: str, action: str, *, requested_by: str | None
    ) -> AccessAnswer:
        """The answer for the person with `email` in `team`, read now, for a service deciding a request on a
        workflow's behalf (tools-service: may the asker decide their own request). The service's `access:view` scope
        and the token's tenant and team stand in for the person caller's access.view; a read changes nothing, so it
        writes no audit entry. 404 when nobody active in the tenant has the address."""
        person = await self.person(tenant, email=email)
        return await self._answer(tenant, team, person.id, area, action, owner=None, requested_by=requested_by)

    async def person(self, tenant: str, *, person_id: str | None = None, email: str | None = None) -> User:
        """The one active person of `tenant` named by id (an admin's check) or by email (a service's): every answer
        is read for a person found here, so a suspended person is not found whichever way they are named. 404
        otherwise."""
        if person_id is not None:
            found = await self.identity.user(tenant, person_id)
        else:
            found = next((u for u in await self.identity.users_by_email(email or "") if u.tenant_id == tenant), None)
        if found is None:
            raise NotFound("No person with that id." if person_id is not None else "No person with that email.")
        return found

    async def why(self, caller: Actor, area: str, action: str) -> AccessAnswer:
        """The caller's own answer for `area.action` in the team they act in, the roles that grant it there, and who
        in the team can give roles, never the caller: what a locked button says. Not audited, as a person reads only
        their own."""
        answer = await self._answer(
            caller.tenant_id, caller.team_id, caller.user_id, area, action, owner=None, requested_by=None
        )
        granting = await self.holders.holders(caller.tenant_id, caller.team_id, area, action)
        admins = await self.holders.holders(
            caller.tenant_id, caller.team_id, "access", "manage", excluding=caller.user_id
        )
        answer["roles"] = [{"id": r.id, "name": r.name} for r in granting.roles]
        answer["askable"] = [h.name for h in admins.holders]
        return answer

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
    ) -> AccessAnswer:
        who = await self.person(tenant, person_id=person_id)
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
        # The built-in roles too, so a refusal names who holds the cell in this workspace.
        await access.grids.load(tenant, version, [*{a.role_id for a in live}, *(r.id for r in BUILTIN_ROLES)])
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
            return {
                "personId": person_id,
                "teamId": team,
                "area": area,
                "action": action,
                "allowed": True,
                "scope": scope,
                "grantedBy": [{**r} for r in granted.roles] if granted else [],
                "refusedBy": None,
            }
        except Forbidden as e:
            return {
                "personId": person_id,
                "teamId": team,
                "area": area,
                "action": action,
                "allowed": False,
                "scope": None,
                "grantedBy": [],
                "refusedBy": {"code": e.code, "reason": e.message},
            }
