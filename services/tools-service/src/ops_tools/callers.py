"""Who is calling, for tools-service's routes, from ops_identity's shared dependency (installed in app.py): the person
behind a console or API-key request, and the service behind an internal call. No route reads identity headers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ops_identity import CurrentPrincipal

from .modules.directory import Directory
from .modules.service import Caller


def caller_in(directory: Directory) -> Callable[..., Awaitable[Caller]]:
    """The caller and their team as the registry sees it; an unknown team falls to the all-scope team."""

    async def caller(p: CurrentPrincipal) -> Caller:
        return Caller(
            tenant_id=p.tenant_id,
            name=p.name,
            team=directory.team(p.team_id),
            roles=dict(p.roles),
            # The dev-header principal is the only one with no roles and auth_method "dev"; a platform token keeps its
            # roles even when platform-service signed the person in through dev sign-in (auth_method "dev").
            verified=p.auth_method != "dev" or bool(p.roles),
        )

    return caller


@dataclass(frozen=True)
class Person:
    """The tenant a tenant-wide setting belongs to and the name recorded on its changes (egress, secrets)."""

    tenant_id: str
    name: str


async def person(p: CurrentPrincipal) -> Person:
    return Person(tenant_id=p.tenant_id, name=p.name)
