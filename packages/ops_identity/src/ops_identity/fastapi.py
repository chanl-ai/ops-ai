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
`X-Team-Id` picks the team, defaulting to the dev seed's `team_all`. `on_principal` runs after each resolution, for a
service that keeps per-request state (agents-service sets its tenant scope there). The mode comes from
`settings.auth_mode` alone, never from whether OPS_PLATFORM_URL is set.

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

from ops_service_kit.settings import Settings

from .http import http_introspect, http_jwks
from .principal import Principal
from .resolve import Identity, ServiceAuth, mint_service_token
from .service_keys import service_signer, service_verifiers

DEV_TENANT = "local"
DEV_TEAM = "team_all"


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
            return cls.for_dev(settings, audience=audience, name=settings.dev_user_name, email=settings.dev_user_email)
        if not settings.platform_url:
            raise ValueError("auth_mode 'platform' needs OPS_PLATFORM_URL")
        http = client or httpx.AsyncClient(timeout=10)
        signer = service_signer(settings)
        identity = Identity(
            audience=audience,
            jwks=http_jwks(http, f"{settings.platform_url.rstrip('/')}/.well-known/jwks.json"),
            # The internal port is reachable from localhost only; introspection comes before a tenant is known.
            introspect=http_introspect(
                http,
                f"http://127.0.0.1:{settings.platform_internal_port}/v1/auth/introspect",
                lambda: mint_service_token(signer, service=audience, audience="platform", tenant_id=None),
            ),
        )
        return cls(identity, ServiceAuth(audience=audience, verifiers=service_verifiers(settings, audience)))

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
    ) -> Auth:
        """The fixed dev user; tests pass their own tenant so each runs on its own rows."""
        dev_user = {"sub": "usr_dev", "email": email, "name": name, "tenant_id": tenant_id, "team_id": team_id}
        # A bearer token in dev finds no key and is refused; dev callers send no token.
        identity = Identity(audience=audience, jwks=_no_keys, introspect=_no_api_keys, dev_user=dev_user)
        return cls(identity, ServiceAuth(audience=audience, verifiers=service_verifiers(settings, audience)))


def install_auth(app: FastAPI, auth: Auth) -> None:
    app.state.ops_auth = auth


def _auth(request: Request) -> Auth:
    auth: Auth | None = getattr(request.app.state, "ops_auth", None)
    if auth is None:
        raise RuntimeError("install_auth(app, ...) was not called for this app")
    return auth


async def current_principal(
    request: Request,
    *,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    x_team_id: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[str | None, Header()] = None,
) -> Principal:
    auth = _auth(request)
    p = await auth.identity.principal(request, authorization, x_api_key, x_team_id, x_dev_user)
    if auth.on_principal is not None:
        auth.on_principal(p)
    return p


async def current_service(request: Request, authorization: Annotated[str | None, Header()] = None) -> Principal:
    auth = _auth(request)
    p = await auth.services.principal(authorization)
    if auth.on_principal is not None:
        auth.on_principal(p)
    return p


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
CurrentService = Annotated[Principal, Depends(current_service)]
