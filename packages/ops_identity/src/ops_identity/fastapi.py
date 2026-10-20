"""The one way a FastAPI service authenticates its callers. Each service builds an `Auth` from its Settings, installs
it on the app, and its routes depend on `CurrentPrincipal` (people and API keys) or `CurrentService` (internal
routes); no service resolves tokens, keys or dev headers itself.

  app = FastAPI(...)
  install_auth(app, Auth.from_settings(settings, audience="tools"))

  @router.get("/v1/things")
  async def things(p: CurrentPrincipal) -> ...: ...

With OPS_AUTH_MODE=platform, tokens are verified against platform-service's key set for the service's audience and
API keys are introspected on its internal port with this service's Ed25519 service token. With `dev` (Settings
refuses it outside dev) every request is the fixed dev user in tenant `local`; `X-Dev-User` names a second person and
`X-Team-Id` picks the team, defaulting to Operations (`team_ops`), as platform-service's dev seed names it.
`on_principal` runs after each resolution, for a service that keeps per-request state (agents-service sets its tenant
scope there). The mode comes from `settings.auth_mode` alone, never from whether OPS_PLATFORM_URL is set.

The service token minted for introspection names the service by its audience, so in production each service's own
key must be bound to that name in platform-service's OPS_SERVICE_PUBLIC_KEYS; a key shared between services is
refused for every name but the one it is bound to. The dev key `svc-dev` is unbound and works for any name, in dev
only. platform-service, the issuer, resolves its own sessions and does not use this module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Header, Request

from ops_service_kit.errors import Forbidden
from ops_service_kit.settings import Settings

from .http import http_introspect, http_jwks
from .principal import Principal
from .resolve import Identity, ServiceAuth, mint_service_token
from .service_keys import service_signer, service_verifiers

DEV_TENANT = "local"
# Operations, under the id platform-service's dev seed gives it: the dev user acts in a team every service knows.
DEV_TEAM = "team_ops"


async def _no_keys() -> dict[str, Any]:
    return {"keys": []}


async def _no_api_keys(_key: str) -> dict[str, Any] | None:
    return None


@dataclass
class Auth:
    identity: Identity
    services: ServiceAuth
    on_principal: Callable[[Principal], None] | None = None

    @classmethod
    def from_settings(cls, settings: Settings, *, audience: str, client: httpx.AsyncClient | None = None) -> Auth:
        if settings.auth_mode != "platform":
            return cls.for_dev(
                settings,
                audience=audience,
                name=settings.dev_user_name,
                email=settings.dev_user_email,
                policies=settings.dev_policies,
            )
        if not settings.platform_url:
            raise ValueError("auth_mode 'platform' needs OPS_PLATFORM_URL")
        http = client or httpx.AsyncClient(timeout=10)
        signer = service_signer(settings)
        internal = settings.platform_internal_url or f"http://127.0.0.1:{settings.platform_internal_port}"
        services = ServiceAuth(
            audience=audience, verifiers=service_verifiers(settings, audience), scopes=settings.service_scopes
        )
        identity = Identity(
            audience=audience,
            jwks=http_jwks(http, f"{settings.platform_url.rstrip('/')}/.well-known/jwks.json"),
            # The internal port is never public; introspection comes before a tenant is known.
            introspect=http_introspect(
                http,
                f"{internal.rstrip('/')}/v1/auth/introspect",
                lambda: mint_service_token(signer, service=audience, audience="platform", tenant_id=None),
            ),
            services=services,
        )
        return cls(identity, services)

    @classmethod
    def for_dev(
        cls,
        settings: Settings,
        *,
        audience: str,
        name: str,
        email: str,
        tenant_id: str = DEV_TENANT,
        team_id: str = DEV_TEAM,
        policies: dict[str, Any] | None = None,
    ) -> Auth:
        """The fixed dev user; tests pass their own tenant so each runs on its own rows. `policies` stand in for the
        tenant's access policies a platform token would carry."""
        dev_user: dict[str, Any] = {
            "sub": "usr_dev",
            "email": email,
            "name": name,
            "tenant_id": tenant_id,
            "team_id": team_id,
            "policies": dict(policies or {}),
        }
        # A person's bearer token in dev finds no key and is refused; dev callers send no token. A service token is
        # verified and capped as in platform mode.
        services = ServiceAuth(
            audience=audience, verifiers=service_verifiers(settings, audience), scopes=settings.service_scopes
        )
        identity = Identity(
            audience=audience, jwks=_no_keys, introspect=_no_api_keys, dev_user=dev_user, services=services
        )
        return cls(identity, services)


def install_auth(app: FastAPI, auth: Auth) -> None:
    app.state.ops_auth = auth


def _auth(request: Request) -> Auth:
    auth: Auth | None = getattr(request.app.state, "ops_auth", None)
    if auth is None:
        raise RuntimeError("install_auth(app, ...) was not called for this app")
    return auth


async def current_caller(
    request: Request,
    *,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    x_team_id: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[str | None, Header()] = None,
) -> Principal:
    """A person, an API key or a service with a scoped token. Only routes that decide with `ops_access.can`, which
    checks a service's scopes, depend on this."""
    auth = _auth(request)
    p = await auth.identity.principal(request, authorization, x_api_key, x_team_id, x_dev_user)
    if auth.on_principal is not None:
        auth.on_principal(p)
    return p


async def current_principal(
    request: Request,
    *,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    x_team_id: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[str | None, Header()] = None,
) -> Principal:
    """A person or an API key. A service token is refused here: these routes decide on roles, which a service has
    none of, so a route opens to services only by depending on `CurrentCaller` and asking `can`."""
    p = await current_caller(
        request, authorization=authorization, x_api_key=x_api_key, x_team_id=x_team_id, x_dev_user=x_dev_user
    )
    if p.kind == "service":
        raise Forbidden("This route does not take service tokens.", code="scope_required")
    return p


async def current_service(request: Request, authorization: Annotated[str | None, Header()] = None) -> Principal:
    auth = _auth(request)
    p = await auth.services.principal(authorization)
    if auth.on_principal is not None:
        auth.on_principal(p)
    return p


async def current_tenant_caller(
    request: Request,
    *,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    x_team_id: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[str | None, Header()] = None,
) -> Principal:
    """`current_caller`, except that a service token need not name a team: for a route whose answer to a service is
    tenant-wide while a person gets their team's (c-222). The route still decides with `ops_access.can`."""
    try:
        return await current_caller(
            request, authorization=authorization, x_api_key=x_api_key, x_team_id=x_team_id, x_dev_user=x_dev_user
        )
    except Forbidden as e:
        if e.code != "team_required":
            raise
        return await current_service(request, authorization)


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
CurrentCaller = Annotated[Principal, Depends(current_caller)]
CurrentService = Annotated[Principal, Depends(current_service)]
CurrentTenantCaller = Annotated[Principal, Depends(current_tenant_caller)]
