"""Who is calling, for tools-service's routes, from ops_identity's shared dependency (installed in app.py): the person
behind a console or API-key request, and the service behind an internal call. No route reads identity headers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Request

from ops_access import Access
from ops_identity import CurrentCaller, Principal
from ops_service_kit.errors import Forbidden

from .modules.directory import Directory
from .modules.policy import FORWARDED
from .modules.service import Caller


def caller_in(directory: Directory) -> Callable[..., Awaitable[Caller]]:
    """The caller and their team as the registry sees it; an unknown team falls to the all-scope team."""

    async def caller(p: CurrentCaller, request: Request) -> Caller:
        _service_reads(p, "tools")
        return Caller(
            tenant_id=p.tenant_id,
            name=p.name,
            team=directory.team(p.team_id),
            roles=dict(p.roles),
            team_role=p.role,
            principal=p,
            # The dev-header principal is the only one with no roles and auth_method "dev"; a platform token keeps its
            # roles even when platform-service signed the person in through dev sign-in (auth_method "dev").
            verified=p.auth_method != "dev" or bool(p.roles),
            credentials={k: v for k in FORWARDED if (v := request.headers.get(k))},
        )

    return caller


def _service_reads(p: Principal, area: str) -> None:
    """A service token (the provisioner, c-180) reaches these routes only holding `<area>:view`, so opening them to it
    does not open them to every service; what it may change, `can` decides from its scopes."""
    if p.kind == "service" and f"{area}:view" not in p.scopes:
        raise Forbidden(f"This service may not read {area}.", code="scope_required")


@dataclass(frozen=True)
class Person:
    """The tenant a tenant-wide setting belongs to and the name recorded on its changes (egress, secrets)."""

    tenant_id: str
    name: str
    # Who it is, for the provisioner-only fields and a system record's protection (c-180); None only in code.
    principal: Principal | None = None


async def tools_reader(p: CurrentCaller) -> Principal:
    """Anyone signed in, or a service holding `tools:view`: the callers of a route with no effects (the formulas)."""
    _service_reads(p, "tools")
    return p


async def person(p: CurrentCaller) -> Person:
    _service_reads(p, "secrets_egress")
    return Person(tenant_id=p.tenant_id, name=p.name, principal=p)


def security_admin(security_team: str) -> Callable[..., Awaitable[Person]]:
    """A person who may change the tenant's egress list: an admin on the Security team. It decides what every tool
    module may reach, so a role in any other team grants nothing here. The dev-header
    principal carries no roles and passes, as it does for module security reviews."""

    async def admin(p: CurrentCaller) -> Person:
        # secrets_egress.manage, held in the Security team: Security admin in the grid (c-149). A team's own secrets
        # are written in that team instead (secrets/routes.py `_may_write`, c-186).
        Access(security_team=security_team).can(
            p, "secrets_egress", "manage", what="the egress list", code="not_security_admin"
        )
        return Person(tenant_id=p.tenant_id, name=p.name, principal=p)

    return admin
