"""Who is calling, for agents-service's routes. Resolution is ops_identity's shared FastAPI layer (installed in
api/app.py), which also enters the request's isolation context (tenant, team, scope) from the verified caller; this
module only adapts its principal. Every router depends on `principal`, which `scripts/check_standards.py` rule 5
checks. Every role rule below is one call to `ops_access.can`, the check every service shares (c-148); the helpers keep
the routes' wording and the record's team and owner."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal

from ops_access import Scope, can, policy
from ops_identity import CurrentCaller, CurrentPrincipal, CurrentService
from ops_identity import Principal as Caller
from ops_policy import STEP_UP_TTL_S, HmacSigner, TokenError, header_of, verify, verify_step_up
from ops_policy.step_up import STEP_UP_TYPE
from ops_service_kit.errors import Forbidden, StepUpRequired

from ..store.tenancy import current_tenant
from .deps import Runtime


@dataclass(frozen=True)
class Principal:
    name: str
    email: str
    team_id: str
    # From the verified token or key, or "local" in dev; never from a header, body or path (I1).
    tenant_id: str
    sub: str = ""
    # The teams the person belongs to; None for the dev principal, which acts across teams.
    team_ids: tuple[str, ...] | None = None
    # The person's role in team_id from their membership (e.g. admin); None for dev callers and keys.
    role: str | None = None
    # Team to role for every team the person belongs to, from the token; a review is decided by the role in the team
    # that reviews it, which need not be the team the request acts in. Empty for dev callers and keys.
    roles: dict[str, str] = field(default_factory=dict[str, str])
    # An API key of one team, not a person: it may start live runs and cancel its own, never decide (c-122).
    is_key: bool = False
    # The verified caller as ops_identity resolved it, which `ops_access.can` decides on; None for a Principal built in
    # code, which `caller_of` rebuilds from the fields above.
    identity: Caller | None = None


async def principal(p: CurrentPrincipal) -> Principal:
    return _principal(p)


async def caller(p: CurrentCaller) -> Principal:
    """A person, an API key, or a service token scoped to one team, for the routes the provisioning service calls
    (c-180); every check on them goes through `can`, which reads a service's scopes."""
    return _principal(p)


def caller_in(area: str) -> Callable[..., Awaitable[Principal]]:
    """`caller` for a router whose reads ask no permission of a person: a service token must still hold `<area>:view`,
    so opening a router to the provisioner does not open its reads to every service."""

    async def dependency(p: CurrentCaller) -> Principal:
        if p.kind == "service":
            can(p, area, "view")
        return _principal(p)

    return dependency


def _principal(p: Caller) -> Principal:
    return Principal(
        name=p.name or p.email,
        email=p.email,
        team_id=p.team_id or "",
        tenant_id=p.tenant_id,
        sub=p.sub,
        # The teams a person approves for. A person platform-service signed in with the dev password also has
        # auth_method "dev" but carries roles; they approve only for their own teams. Only the dev header caller,
        # which has no roles, approves for any.
        team_ids=None if p.auth_method == "dev" and not p.roles else tuple(p.team_ids),
        role=p.role,
        roles=dict(p.roles),
        is_key=p.auth_method == "api_key",
        identity=p,
    )


def caller_of(me: Principal) -> Caller:
    """What `ops_access.can` decides on: the verified principal, or one rebuilt from the fields of a Principal made in
    code (no teams: the dev header caller, which acts across teams)."""
    if me.identity is not None:
        return me.identity
    roles = dict(me.roles) or ({me.team_id: me.role} if me.role and me.team_id else {})
    method = "dev" if me.team_ids is None else "api_key" if me.is_key else "session"
    return Caller(
        kind="api_key" if me.is_key else "person",
        sub=me.sub,
        email=me.email,
        name=me.name,
        tenant_id=me.tenant_id,
        team_id=me.team_id or None,
        team_ids=list(me.team_ids or ()),
        roles={} if method == "dev" else roles,
        scopes=[],
        auth_method=method,
    )


@dataclass(frozen=True)
class Service:
    name: str


async def service_principal(p: CurrentService) -> Service:
    """Internal routes (the timer fire) are for schedulers, not people: an Ed25519 service token for audience
    "agents" that names the tenant it acts for (I13)."""
    return Service(name=p.sub)


# The console's mock sign-in uses these for every demo account (apps/console/src/lib/api/mock/auth/seed.ts). Dev mode
# only, like the rest of this module: real auth re-authenticates against the identity provider instead.
DEV_PASSWORD = "northfield-demo"
DEV_TOTP = "123456"


def step_up_signer(rt: Runtime) -> HmacSigner:
    """Derived from the review key for this one purpose, so an approval token can never pass as a step-up."""
    return HmacSigner.derived(rt.settings.review_key.get_secret_value(), "step-up")


def step_up_ref(token: str | None) -> str | None:
    """What is recorded on a decision: a fingerprint of the step-up, which identifies it without being reusable."""
    return "su:" + hashlib.sha256(token.encode()).hexdigest()[:32] if token else None


def require_step_up(rt: Runtime, subject: str, token: str | None) -> None:
    """Refuses unless `token` is a step-up for `subject` from the last five minutes: one this service minted (dev
    sign-in), or one platform-service issued after a password re-check (EdDSA, under its session key)."""
    if not (token or "").strip():
        raise StepUpRequired(
            "Re-authenticate to approve this: its approval policy asks each approver for a step-up first."
        )
    try:
        if header_of(token or "").get("alg") == "EdDSA":
            verify_platform_step_up(rt, subject, token or "")
        else:
            verify_step_up(token or "", subject, step_up_signer(rt))
    except TokenError as e:
        raise StepUpRequired(f"The step-up was refused ({e.reason}): {e} Re-authenticate and try again.") from e


def verify_platform_step_up(rt: Runtime, subject: str, token: str) -> None:
    """platform-service's POST /v1/auth/step-up token: signed with the key that signed the caller's session, for this
    service's audience, `typ` step_up, naming the deciding person by email in the request's tenant, under five minutes
    old. The key comes from the shared Auth's cache with no fetch: the caller's own token loaded it, so a step-up
    under a kid the cache does not hold is refused rather than looked up."""
    keys = rt.platform_keys.keys if rt.platform_keys is not None else None
    verifier = (keys or {}).get(str(header_of(token).get("kid", "")))
    if verifier is None:
        raise TokenError("signature", "The step-up was not issued by the identity service this service trusts.")
    claims = verify(token, verifier)
    if claims.get("typ") != STEP_UP_TYPE:
        raise TokenError("type", "That token is not a step-up token.")
    if claims.get("email") != subject or claims.get("tenant_id") != current_tenant():
        raise TokenError("subject", "The step-up was made by someone else.")
    if time.time() - int(claims["iat"]) > STEP_UP_TTL_S:
        raise TokenError("too_old", f"The step-up is older than {STEP_UP_TTL_S // 60} minutes; re-authenticate.")


def teams_of(me: Principal) -> list[str] | None:
    """The teams a person belongs to, in any role; None for the dev principal, which acts across teams."""
    return None if me.team_ids is None else list(me.team_ids)


def review_teams(me: Principal) -> list[str] | None:
    """The teams whose reviews a person decides (`reviews.decide` held there). None for the dev header caller, which
    acts across teams; an API key decides for none."""
    if me.team_ids is None:
        return None
    who = caller_of(me)
    return [t for t in me.team_ids if not me.is_key and _held(who, "reviews", "decide", t)]


def _held(who: Caller, area: str, action: str, team: str) -> Scope | None:
    try:
        return can(who, area, action, team=team, from_any_team=True)
    except Forbidden:
        return None


def require_reviews_decide(approver_teams: list[str] | None, team_id: str, what: str) -> None:
    """reviews.decide in the team that reviews it: `approver_teams` is `review_teams`, the teams where `can` grants it,
    from whatever team the request acts in. Separation of duties and step-up are checked where the decision is
    recorded."""
    if approver_teams is None or team_id in approver_teams:
        return
    raise Forbidden(
        f"Only a reviewer or admin of {team_id} decides {what}.",
        code="role_required",
        details={"teamId": team_id, "area": "reviews", "action": "decide"},
    )


def workspace_step_up(me: Principal) -> bool:
    """Whether the workspace asks every approver for a step-up (the `stepUp` policy, c-186, off by default). It adds
    to an operation's own stepUp and never removes it."""
    return bool(policy(caller_of(me), "stepUp"))


def require_not_own(me: Principal, requested_by: Iterable[str | None], *, team: str | None, what: str) -> None:
    """Separation of duties on a decision, decided by `can` (c-186): whoever asked for, saved or started what `me`
    decides does not decide it while the tenant's requesterMayDecide policy is off. Runs after the role check; `team` is
    a team the decision's role is held in, or None for one of the caller's reviewing teams. A workflow's own principal
    (`workflow:<id>`) asking is refused whatever the policy: no person holds that identity, so only a forged one could
    decide with it."""
    held = team or next(iter(review_teams(me) or ()), None) or me.team_id
    asked = tuple(requested_by)
    workflows = tuple(a for a in asked if a and a.startswith("workflow:"))
    can(
        caller_of(me),
        "reviews",
        "decide",
        team=held,
        from_any_team=True,
        not_by=workflows,
        requested_by=asked,
        what=what,
    )


# Route wording to catalogue action: a definition is created, published or deleted; every other change (a save, a
# pause, a restore, a test run, a migration, an event or message posted to a thread) edits it, and polling a deployment
# runs it.
_ACTIONS = {"create": "create", "publish": "publish", "delete": "delete", "poll": "run"}


def require_builder(
    me: Principal,
    *,
    area: str,
    team_id: str | None,
    action: str,
    what: str,
    protection: str | None = None,
) -> None:
    """Who may change a definition (an agent, workflow, guardrail, skill, widget or deployment): `can(area, action)` in
    the team that owns it, which must be the team the request acts in (R6), and for a record no team owns (a shared
    one, such as a seeded event workflow) in the team the request acts in. The roles grid decides it either way; an API
    key holds none of these cells (R4). `protection` is the record's (c-180): a `system` record is changed by the
    provisioning service only."""
    can(caller_of(me), area, _ACTIONS.get(action, "edit"), team=team_id or None, what=what, protection=protection)


def require_runs_start(me: Principal, *, team_id: str | None, what: str) -> None:
    """workflows.run: a live run, by a builder or admin of the workflow's team (the acting team when none owns it), or
    an API key of that team (c-122 Q1). A test run is `require_builder(..., action="test")`, which keys never pass."""
    can(caller_of(me), "workflows", "run", team=team_id or None, what=what)


def started_by(me: Principal) -> str:
    """What a run or thread records as who started it: `key:<id>` for an API key (c-246), so each key's traffic is
    counted and its runs are its own; a person's email otherwise."""
    key = me.identity.key_id if me.is_key and me.identity is not None else None
    return f"key:{key}" if key else me.email


def require_key_reaches(me: Principal, kind: Literal["agent", "workflow"], target_id: str) -> int | None:
    """An API key scoped to one agent or workflow (c-246) starts that one only, whatever the request names; the target
    comes from introspection, never the request. Returns the workflow version the key pins, None to run the live one
    (and for every caller that is not a scoped key)."""
    target = me.identity.key_target if me.is_key and me.identity is not None else None
    if not target:
        return None
    if (target.get("kind"), target.get("id")) != (kind, target_id):
        raise Forbidden(
            f"This API key starts only {target.get('kind')} {target.get('id')}.",
            code="key_target",
            details={"target": target},
        )
    version = target.get("version")
    return int(version) if version is not None else None


def key_scope(me: Principal) -> tuple[str, str] | None:
    """The (kind, id) a scoped API key reaches (c-246): it starts and reads that one only. None for everyone else."""
    target = me.identity.key_target if me.is_key and me.identity is not None else None
    return (str(target.get("kind")), str(target.get("id"))) if target else None


def graph_target(graph: str) -> tuple[Literal["agent", "workflow"], str]:
    """A graph thread's agent (`agent:<id>`) or workflow, as a key's target names it."""
    return ("agent", graph.removeprefix("agent:")) if graph.startswith("agent:") else ("workflow", graph)


def require_runs_cancel(me: Principal, *, team_id: str, started_by: str, what: str) -> None:
    """cases.manage: whoever started the run (`own`), or an admin or reviewer of its team (c-122 Q2); a key cancels only
    runs started under its own identity."""
    can(caller_of(me), "cases", "manage", team=team_id, owner=started_by, what=what)


def require_chat_use(me: Principal, *, team_id: str | None) -> None:
    """chat.run: every role of the agent's team chats with it, viewers included; a person acting in another team is
    refused with the team named (c-122 Q4). An agent no team owns (`team_id` None) is open to every team."""
    if team_id:
        can(caller_of(me), "chat", "run", team=team_id, what="this agent")
