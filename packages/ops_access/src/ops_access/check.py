"""`can`: the one answer to "may this caller do this" that every service gives.

A caller is one of four kinds, each read from its verified token by `ops_identity`:

| Caller | What it holds |
|---|---|
| Person | Role ids per team (`Principal.access`, from the token's `access` claim); a token without it maps `roles` |
| API key | `KEY_GRANTS` in its own team only: start a live run, cancel the runs it started, run the team's tools |
| Service | The `area:action` scopes its service token lists; nothing else |
| Dev header caller | Every role rule, in dev only (`ops_identity` refuses dev headers); its own records only |

A person's action is held in the team the record belongs to, which must be the team the request acts in (403
`team_forbidden` naming it otherwise), except the Security team's actions (`SECURITY_TEAM_ACTIONS`), held in the
Security team whatever team the request acts in. Scope `own` passes only for a record whose `owner` is the caller.
`not_by` names people who may never take the action, such as an earlier approver of a two-person decision (403
`own_request`); `requested_by` names who asked for it (or saved or started it), refused the same way only while the
tenant's `requesterMayDecide` policy is off (c-186). Both are separation of duties, not role rules, so they bind the
dev header caller too. A token
without the `access` claim maps `roles` through the membership mapping, which c-147's grid test proved equal.

The grid for a role id comes from `Grids`, cached by (tenant, permission version): the version rises with every role,
assignment or membership change, so a cached grid is never stale for the token that carries its version. Built-in
roles answer from code; a custom role (c-151) needs a fetcher.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ops_identity import Principal
from ops_service_kit.errors import Forbidden
from ops_service_kit.settings import Settings

from .catalogue import (
    ACTIONS,
    ANY_TEAM,
    AREAS,
    BUILTIN_ROLES,
    SECURITY_TEAM_ACTIONS,
    Grant,
    Scope,
    builtin_roles_for,
)
from .policies import policy

BUILTIN_GRIDS: dict[str, tuple[Grant, ...]] = {r.id: r.grants for r in BUILTIN_ROLES}
BUILTIN_NAMES = {r.id: r.name for r in BUILTIN_ROLES}
_CELLS = frozenset((a, x) for a in AREAS for x in ACTIONS)

# An API key is a bank system acting for one team (c-122 Q1 and Q2): it starts live runs and cancels the runs it
# started, and runs the team's tools (owner, 2026-10-19, c-354 Q4: over MCP a key lists and runs read tools; a write
# always waits for a person). It never decides, edits, test-runs or reads another team's records.
KEY_GRANTS: dict[tuple[str, str], Scope] = {
    ("workflows", "run"): "all",
    ("cases", "manage"): "own",
    ("tools", "run"): "all",
}

FetchGrids = Callable[[str, int, list[str]], Awaitable[Mapping[str, Iterable[Grant]]]]


@dataclass
class Grids:
    """Role id to grants. Built-in roles from code; others from `fetch` (tenant, version, role ids), cached per
    (tenant, version) and dropped when a newer version is seen for the tenant."""

    fetch: FetchGrids | None = None
    _cache: dict[str, tuple[int, dict[str, tuple[Grant, ...]]]] = field(
        default_factory=dict[str, tuple[int, dict[str, tuple[Grant, ...]]]]
    )

    def known(self, tenant_id: str, version: int | None, role_ids: Iterable[str]) -> dict[str, tuple[Grant, ...]]:
        """The grids `can` uses synchronously: built-in roles and whatever the cache holds for this version."""
        cached = self._cache.get(tenant_id)
        extra = cached[1] if cached and cached[0] == version else {}
        return {r: BUILTIN_GRIDS.get(r) or extra.get(r, ()) for r in role_ids}

    async def load(self, tenant_id: str, version: int | None, role_ids: Iterable[str]) -> None:
        """Fetches the custom roles the cache lacks for this version; a no-op for built-in roles or with no fetcher."""
        missing = [r for r in role_ids if r not in BUILTIN_GRIDS]
        cached = self._cache.get(tenant_id)
        have = cached[1] if cached and cached[0] == version else {}
        missing = [r for r in missing if r not in have]
        if not missing or self.fetch is None or version is None:
            return
        fetched = await self.fetch(tenant_id, version, missing)
        self._cache[tenant_id] = (version, {**have, **{r: tuple(g) for r, g in fetched.items()}})


@dataclass
class Access:
    """`can` with this deployment's Security team and grid source. Services build one at startup."""

    # The deployment's security team (settings `security_team_id`), for a token that does not name its workspace's.
    security_team: str = field(default_factory=lambda: Settings().security_team_id)
    grids: Grids = field(default_factory=Grids)

    def security_team_of(self, p: Principal) -> str:
        """The caller's workspace security team, from their token (c-202); the deployment's when the token has none."""
        return p.security_team or self.security_team

    def roles_in(self, p: Principal, team: str) -> list[str]:
        """The role ids the person holds in `team`."""
        if p.access:
            return list(dict.fromkeys([*p.access.get(team, ()), *p.access.get(ANY_TEAM, ())]))
        role = p.roles.get(team)
        return list(builtin_roles_for(role, security_team=team == self.security_team_of(p))) if role else []

    def scope(self, p: Principal, area: str, action: str, team: str) -> Scope | None:
        """The widest scope the person's roles in `team` grant for the action, or None. While the workspace keeps chat
        threads private (`chatThreadsOwnerOnly`, on by default) a chat read is one's own whatever the grid says."""
        grids = self.grids.known(p.tenant_id, p.permission_version, self.roles_in(p, team))
        scopes = {s for grants in grids.values() for a, x, s in grants if (a, x) == (area, action)}
        widest: Scope | None = "all" if "all" in scopes else "own" if "own" in scopes else None
        if widest == "all" and (area, action) == ("chat", "view") and policy(p, "chatThreadsOwnerOnly"):
            return "own"
        return widest

    def _may_change_system(
        self, p: Principal, area: str, *, team: str | None, owner: str | None, what: str, from_any_team: bool
    ) -> None:
        try:
            self.can(p, area, "manage", team=team, owner=owner, what=what, from_any_team=from_any_team)
        except Forbidden as e:
            raise Forbidden(
                f"{what} is a system record the platform provisions; changing it needs {area}.manage (admins).",
                code="system_record",
            ) from e

    def can(
        self,
        p: Principal,
        area: str,
        action: str,
        *,
        team: str | None = None,
        owner: str | None = None,
        not_by: Iterable[str | None] = (),
        requested_by: Iterable[str | None] = (),
        what: str = "this",
        from_any_team: bool = False,
        code: str = "role_required",
        protection: str | None = None,
        speaking_of: str | None = None,
    ) -> Scope:
        """Returns the scope the caller holds, or raises 403. `team` is the team that owns the record (None: the team
        the request acts in, for a create); `owner` is the record's owner or creator (email), for `own` scope.
        `from_any_team` reads the role in `team` whatever team the request acts in: a review is decided by the role in
        the team that reviews it (c-122). `code` is the error code a role refusal carries, for a route that documented
        its own before `can` (`not_team_admin`, `builder_only`). `protection` is the record's (c-180): editing or
        deleting a `system` record also needs `<area>.manage`, which the grid gives admins and not builders; the
        provisioning service needs only its scopes, and its next run puts back the fields the template owns.
        `speaking_of` names the person when someone else asks on their behalf (an admin's Check access): a refusal then
        says "Maya asked for this" instead of "You asked for this"."""
        you, your, own = (speaking_of, f"{speaking_of}'s", "their") if speaking_of else ("You", "Your", "your")
        if (area, action) not in _CELLS:
            raise ValueError(f"{area}.{action} is not in the catalogue")
        if protection == "system" and action in PROTECTED_ACTIONS and p.kind != "service":
            self._may_change_system(p, area, team=team, owner=owner, what=what, from_any_team=from_any_team)
        if p.kind == "service":
            return _service(p, area, action, team)
        refused = [*not_by, *(requested_by if not policy(p, "requesterMayDecide") else ())]
        if any(n and n.lower() in (p.email.lower(), p.sub.lower()) for n in refused):
            raise Forbidden(f"{you} asked for {what}, so someone else has to decide it.", code="own_request")
        if p.auth_method == "dev" and not p.roles and not p.access:
            # The dev header caller holds no role, so it passes every role rule; on a record with an owner it acts on
            # its own only, as every service treated it before `can` (chat reads, rule and knowledge changes).
            if owner is not None and owner.strip().lower() != p.email.strip().lower():
                raise Forbidden(
                    f"The dev caller changes only what it created; {what} is someone else's.", code="role_required"
                )
            return "all"
        if p.kind == "api_key":
            return _key(p, area, action, team=team, owner=owner, what=what)
        held_in = self.security_team_of(p) if (area, action) in SECURITY_TEAM_ACTIONS else team or p.team_id
        if held_in is None:
            raise Forbidden("Choose a team with the X-Team-Id header.", code="team_required")
        if (area, action) not in SECURITY_TEAM_ACTIONS and not from_any_team:
            _same_team(p, held_in, action, what)
        scope = self.scope(p, area, action, held_in)
        if scope is None:
            raise Forbidden(
                f"{your} roles in {held_in} do not allow {area}.{action} on {what}.",
                code=code,
                details={
                    "teamId": held_in,
                    "area": area,
                    "action": action,
                    "roles": self.roles_in(p, held_in),
                    "grantedBy": [r.id for r in BUILTIN_ROLES if any((a, x) == (area, action) for a, x, _ in r.grants)],
                },
            )
        if scope == "own" and owner is not None and owner.strip().lower() != p.email.strip().lower():
            raise Forbidden(
                f"{your} roles in {held_in} allow {area}.{action} on {own} own records only.",
                code="role_required",
                details={"teamId": held_in, "area": area, "action": action, "scope": "own"},
            )
        return scope

    def may(self, p: Principal, area: str, action: str, **record: Any) -> bool:
        """`can` as a yes or no, for a response that tells the caller what they may do with a record (c-186)."""
        try:
            self.can(p, area, action, **record)
        except Forbidden:
            return False
        return True


def _same_team(p: Principal, team: str, action: str, what: str) -> None:
    if p.team_id != team:
        raise Forbidden(
            f"{what} belongs to team {team}; act in that team to {action} it.",
            code="team_forbidden",
            details={"teamId": team},
        )


def _service(p: Principal, area: str, action: str, team: str | None) -> Scope:
    if f"{area}:{action}" not in p.scopes:
        raise Forbidden(
            f"This service token does not hold the {area}:{action} scope.",
            code="scope_required",
            details={"scope": f"{area}:{action}"},
        )
    if team is not None:
        if p.team_id is None:
            # A token with no team acts tenant-wide only (a scan verdict); a team's record needs the team signed in.
            raise Forbidden("A service token for a team's record names that team.", code="team_required")
        _same_team(p, team, action, "this record")
    return "all"


def _key(p: Principal, area: str, action: str, *, team: str | None, owner: str | None, what: str) -> Scope:
    scope = KEY_GRANTS.get((area, action))
    if scope is None:
        raise Forbidden(
            f"An API key cannot {action} {what}; a person with the role must.",
            code="role_required",
            details={"area": area, "action": action},
        )
    _same_team(p, team or str(p.team_id), action, what)
    # A key's runs record `key:<id>` (c-246); older ones its creator's email.
    mine = {p.email.strip().lower(), *([f"key:{p.key_id}".lower()] if p.key_id else [])}
    if scope == "own" and owner is not None and owner.strip().lower() not in mine:
        raise Forbidden(f"An API key may {action} only what it started.", code="role_required")
    return scope


DEFAULT = Access()


def can(
    p: Principal,
    area: str,
    action: str,
    *,
    team: str | None = None,
    owner: str | None = None,
    not_by: Iterable[str | None] = (),
    requested_by: Iterable[str | None] = (),
    what: str = "this",
    from_any_team: bool = False,
    code: str = "role_required",
    protection: str | None = None,
) -> Scope:
    """`Access.can` with the default Security team; services with another call their own `Access`."""
    return DEFAULT.can(
        p,
        area,
        action,
        team=team,
        owner=owner,
        not_by=not_by,
        requested_by=requested_by,
        what=what,
        from_any_team=from_any_team,
        code=code,
        protection=protection,
    )


# A system record refuses these to anyone but the provisioner; viewing, running and deciding stay open.
PROTECTED_ACTIONS = frozenset({"edit", "delete"})
PROTECTIONS = ("system", "managed")


def require_provisioner(p: Principal, area: str) -> None:
    """Only the provisioning service sets a record's `templateId` or `protection` (c-180): a service token holding
    `<area>:provision`. A person or an API key sending either field is refused, so nobody locks a record or takes over a
    template's slot."""
    if p.kind != "service" or f"{area}:provision" not in p.scopes:
        raise Forbidden(
            f"Only the provisioning service sets a template id or protection on {area}.", code="provisioner_only"
        )
