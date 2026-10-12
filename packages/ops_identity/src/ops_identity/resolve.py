"""The FastAPI dependencies that turn a request into a `Principal`.

`Identity.principal` serves public routes. Its resolution order is spec section 4's:
1. `Authorization: Bearer <platform token>`: verified locally against the cached key set, for this service's audience
   (I14).
2. An API key, as `X-API-Key: ok_…` or `Authorization: Bearer ok_…`: introspected by platform-service and cached
   for `key_cache_s`, so a revocation takes effect within that time.
3. Dev mode, only when the service was built with a `dev_user`.

The team comes from `X-Team-Id`, chosen among the identity's teams and never trusted on its own (I1). An API key's
scopes are enforced here from the HTTP method, so no route can forget to: a read key is refused on every method
that writes (I9).

`ServiceAuth.principal` serves internal routes only. It accepts only service tokens, signed with a calling service's
own key and never with the key user tokens are signed with, so neither kind of token works on the other's routes,
and a key bound to one service cannot speak for another (I13).
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated, Any

from fastapi import Header, Request

from ops_policy import Ed25519Signer, Ed25519Verifier, TokenError, header_of, mint, verify
from ops_service_kit.errors import Forbidden, Unauthorized, ValidationFailed

from .jwks import JwksCache, JwksFetch
from .principal import Principal

Introspect = Callable[[str], Awaitable[dict[str, Any] | None]]
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
KEY_PREFIX = "ok_"


def _refused() -> Unauthorized:
    return Unauthorized("Sign in, or send a valid API key.")


def _pick_team(team_ids: list[str], requested: str | None) -> str:
    if requested is None:
        if len(team_ids) != 1:
            raise ValidationFailed("Choose a team with the X-Team-Id header.", code="team_required")
        return team_ids[0]
    if requested not in team_ids:
        raise Forbidden("You are not a member of that team.", code="team_forbidden")
    return requested


class Identity:
    def __init__(
        self,
        *,
        audience: str,
        jwks: JwksFetch,
        introspect: Introspect,
        dev_user: dict[str, str] | None = None,
        key_cache_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not audience:
            raise ValueError("an Identity needs the audience its service verifies tokens for")
        self.audience = audience
        self.keys = JwksCache(jwks, audience, clock=clock)
        self.introspect = introspect
        self.dev_user = dev_user
        self.key_cache_s = key_cache_s
        self.clock = clock
        # Keyed by the key's SHA-256, so no key text is held in memory beyond the request.
        self._key_cache: dict[str, tuple[float, Principal]] = {}

    async def principal(
        self,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        x_api_key: Annotated[str | None, Header()] = None,
        x_team_id: Annotated[str | None, Header()] = None,
        x_dev_user: Annotated[str | None, Header()] = None,
    ) -> Principal:
        scheme, _, bearer = (authorization or "").partition(" ")
        token = bearer if scheme.lower() == "bearer" and bearer else None
        if x_api_key or (token and token.startswith(KEY_PREFIX)):
            p = await self._from_key(x_api_key or token or "", x_team_id)
            if "write" not in p.scopes and request.method.upper() not in READ_METHODS:
                raise Forbidden("This API key may only read.", code="scope_required")
            return p
        if token:
            return await self._from_token(token, x_team_id)
        if self.dev_user is not None:
            return self._dev(x_dev_user, x_team_id)
        raise _refused()

    async def _from_token(self, token: str, team: str | None) -> Principal:
        try:
            kid = str(header_of(token).get("kid", ""))
            verifier = await self.keys.verifier(kid)
            if verifier is None:
                raise _refused()
            claims = verify(token, verifier)
        except TokenError as e:
            raise _refused() from e
        if claims.get("kind", "person") != "person":
            raise _refused()
        named: list[Any] = claims.get("team_ids") or []
        team_ids = [str(t) for t in named]
        roles_claim: dict[str, Any] = claims.get("roles") or {}
        return Principal(
            kind="person",
            sub=str(claims["sub"]),
            email=str(claims.get("email", "")),
            name=str(claims.get("name", "")),
            tenant_id=str(claims["tenant_id"]),
            team_id=_pick_team(team_ids, team),
            team_ids=team_ids,
            roles={str(k): str(v) for k, v in roles_claim.items()},
            scopes=[],
            auth_method="session" if claims.get("auth_method") != "dev" else "dev",
        )

    async def _from_key(self, api_key: str, team: str | None) -> Principal:
        digest = hashlib.sha256(api_key.encode()).hexdigest()
        now = self.clock()
        cached = self._key_cache.get(digest)
        if cached is not None and cached[0] > now:
            p = cached[1]
        else:
            found = await self.introspect(api_key)
            if found is None:
                self._key_cache.pop(digest, None)
                raise _refused()
            p = Principal(
                kind="api_key",
                sub=str(found["sub"]),
                email=str(found.get("email", "")),
                name=str(found.get("name", "")),
                tenant_id=str(found["tenantId"]),
                team_id=str(found["teamId"]),
                team_ids=[str(found["teamId"])],
                roles={},
                scopes=[str(s) for s in found.get("scopes", [])],
                auth_method="api_key",
            )
            if self.key_cache_s > 0:
                self._key_cache[digest] = (now + self.key_cache_s, p)
        if team is not None and team != p.team_id:
            raise Forbidden("This API key is bound to another team.", code="team_forbidden")
        return p

    def _dev(self, email: str | None, team: str | None) -> Principal:
        """The fixed dev user; `X-Dev-User` names a second person (email and name), and `X-Team-Id` picks the team,
        defaulting to the dev user's own."""
        user = self.dev_user or {}
        chosen = team or user.get("team_id")
        return Principal(
            kind="person",
            sub=user.get("sub", "usr_dev"),
            email=email or user.get("email", ""),
            name=email or user.get("name", ""),
            tenant_id=user.get("tenant_id", "local"),
            team_id=chosen,
            team_ids=[chosen] if chosen else [],
            roles={},
            scopes=[],
            auth_method="dev",
        )


class ServiceAuth:
    """Internal routes. `verifiers` maps each trusted kid to its verifier and the service bound to it (None: any).
    `tenant_scoped` mounts require the tenant the call acts for; introspection runs before a tenant is known and is
    the one mount built without it."""

    def __init__(
        self, *, audience: str, verifiers: Mapping[str, tuple[Ed25519Verifier, str | None]], tenant_scoped: bool = True
    ) -> None:
        if any(v.audience != audience for v, _ in verifiers.values()):
            raise ValueError("every service verifier must be bound to this service's audience")
        self.audience = audience
        self.verifiers = dict(verifiers)
        self.tenant_scoped = tenant_scoped

    async def principal(self, authorization: Annotated[str | None, Header()] = None) -> Principal:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise Unauthorized("This route is internal and needs a service token.")
        try:
            trusted = self.verifiers.get(str(header_of(token).get("kid", "")))
            if trusted is None:
                raise _refused()
            verifier, bound = trusted
            claims = verify(token, verifier)
        except TokenError as e:
            raise _refused() from e
        sub = str(claims.get("sub", ""))
        tenant = claims.get("tenant_id")
        if claims.get("kind") != "service" or not sub.startswith("service:"):
            raise _refused()
        if bound is not None and sub != f"service:{bound}":
            raise _refused()
        if self.tenant_scoped and not tenant:
            raise _refused()
        return Principal(
            kind="service",
            sub=sub,
            email="",
            name=sub,
            tenant_id=str(tenant or ""),
            team_id=None,
            team_ids=[],
            roles={},
            scopes=[],
            auth_method="service",
        )


def mint_service_token(
    signer: Ed25519Signer, *, service: str, audience: str, tenant_id: str | None, ttl_s: int = 60
) -> str:
    """A short token one service presents to another's internal routes, naming the tenant it acts for as a claim;
    None only for introspection, which comes before a tenant is known."""
    claims: dict[str, Any] = {"sub": f"service:{service}", "kind": "service", "aud": audience}
    if tenant_id is not None:
        claims["tenant_id"] = tenant_id
    return mint(claims, signer, ttl_s=ttl_s)
