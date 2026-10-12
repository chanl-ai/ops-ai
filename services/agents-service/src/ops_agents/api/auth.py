"""Who is calling, for agents-service's routes. Resolution is ops_identity's shared FastAPI layer (installed in
api/app.py); this module only adapts its principal and sets the request's tenant and team for the stores
(store/tenancy.py). Every router depends on `principal`, which `scripts/check_standards.py` rule 5 checks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ops_identity import CurrentPrincipal, CurrentService
from ops_policy import HmacSigner, TokenError, verify_step_up
from ops_service_kit.errors import StepUpRequired

from ..store.tenancy import set_team, set_tenant
from .deps import Runtime


@dataclass(frozen=True)
class Principal:
    name: str
    email: str
    team_id: str
    # From the verified token or key, or "local" in dev; never from a header, body or path (I1).
    tenant_id: str
    sub: str = ""


async def principal(p: CurrentPrincipal) -> Principal:
    set_tenant(p.tenant_id)
    # Team access is held for platform callers only. Dev acts across teams, as it always has: the console sends its
    # selected team while scripts and seeds create threads in team_all.
    set_team(None if p.auth_method == "dev" else p.team_id)
    return Principal(name=p.name or p.email, email=p.email, team_id=p.team_id or "", tenant_id=p.tenant_id, sub=p.sub)


@dataclass(frozen=True)
class Service:
    name: str


async def service_principal(p: CurrentService) -> Service:
    """Internal routes (the timer fire) are for schedulers, not people: an Ed25519 service token for audience
    "agents" that names the tenant it acts for (I13)."""
    set_tenant(p.tenant_id)
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
    """Refuses unless `token` is a step-up this service minted for `subject` in the last five minutes."""
    if not (token or "").strip():
        raise StepUpRequired("Re-authenticate to approve this money movement: it needs a step-up first.")
    try:
        verify_step_up(token or "", subject, step_up_signer(rt))
    except TokenError as e:
        raise StepUpRequired(f"The step-up was refused ({e.reason}): {e} Re-authenticate and try again.") from e
