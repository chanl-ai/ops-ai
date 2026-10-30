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
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Annotated, Any, cast

from fastapi import Header, Request

from ops_policy import Ed25519Signer, Ed25519Verifier, TokenError, header_of, mint, verify
from ops_service_kit.errors import Forbidden, Unauthorized, ValidationFailed

from .acting_for import ActingForPerson, person_of
from .acting_for import refused as acting_for_refused
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
        dev_user: dict[str, Any] | None = None,
        services: ServiceAuth | None = None,
        key_cache_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not audience:
            raise ValueError("an Identity needs the audience its service verifies tokens for")
        self.audience = audience
        self.keys = JwksCache(jwks, audience, clock=clock)
        self.introspect = introspect
        self.dev_user = dev_user
        # Service tokens on public routes: verified against the service keys and capped by their scopes (c-167).
        self.services = services
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
        if token and self.services is not None and self.services.signs(token):
            return self._from_service(token, x_team_id)
        if token:
            return await self._from_token(token, x_team_id)
        if self.dev_user is not None:
            return self._dev(x_dev_user, x_team_id)
        raise _refused()

    async def bearer(self, authorization: str | None, team: str | None = None) -> Principal:
        """The caller behind `Authorization: Bearer` on a route FastAPI does not resolve (tools-service's MCP adapter,
        c-356): an API key or a person's token, acting in `team` (403 `team_forbidden` when the key or token is not in
        it). No HTTP-method read gate: every MCP request is a POST, and that route keeps a key to what it may run. A
        service token, the dev caller and a missing credential are refused."""
        scheme, _, given = (authorization or "").partition(" ")
        token = given if scheme.lower() == "bearer" and given else None
        if token is None:
            raise _refused()
        if token.startswith(KEY_PREFIX):
            return await self._from_key(token, team)
        if self.services is not None and self.services.signs(token):
            raise _refused()
        return await self._from_token(token, team)

    async def acting_for(self, token: str, caller: Principal) -> ActingForPerson:
        """The person `caller` (a service) says its call acts for, from the acting-for token platform-service signed
        (c-558): its own `kind`, minted for this service, in the call's tenant and team. In dev a token the calling
        service signed itself is accepted instead, since no platform-service runs; a platform stack never takes one."""
        if caller.kind != "service":
            raise acting_for_refused("only a service call names whom it acts for")
        try:
            kid = str(header_of(token).get("kid", ""))
            verifier = await self.keys.verifier(kid)
            if verifier is None and self.dev_user is not None and self.services is not None:
                trusted = self.services.verifiers.get(kid)
                verifier = trusted[0] if trusted is not None else None
            if verifier is None:
                raise acting_for_refused("it is not signed by platform-service")
            claims = verify(token, verifier)
        except TokenError as e:
            raise acting_for_refused("it does not verify") from e
        return person_of(claims, service=caller.sub, tenant_id=caller.tenant_id, team_id=caller.team_id)

    def _from_service(self, token: str, team: str | None) -> Principal:
        """A service on a public route acts in the one team its signed token names; a header never widens it."""
        assert self.services is not None
        p = self.services.resolve(token)
        if not p.tenant_id:
            raise _refused()
        if p.team_id is None:
            raise Forbidden("A service token on this route names its team.", code="team_required")
        if team is not None and team != p.team_id:
            raise Forbidden("The service token is bound to another team.", code="team_forbidden")
        return p

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
        access_claim: dict[str, Any] = claims.get("access") or {}
        version = claims.get("perm_version")
        policies: dict[str, Any] = claims.get("policies") or {}
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
            access={str(k): [str(r) for r in v] for k, v in access_claim.items()},
            permission_version=int(version) if isinstance(version, int) else None,
            policies={str(k): v for k, v in policies.items()},
            security_team=str(claims["security_team"]) if claims.get("security_team") else None,
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
            key = cast(dict[str, Any], found.get("apiKey") or {})
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
                policies=dict(found.get("policies") or {}),
                key_id=str(key.get("id") or "") or None,
                key_target=cast(dict[str, Any] | None, key.get("target")) or None,
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
            policies=dict(user.get("policies") or {}),
        )


class ServiceAuth:
    """Internal routes. `verifiers` maps each trusted kid to its verifier and the service bound to it (None: any).
    `tenant_scoped` mounts require the tenant the call acts for; introspection runs before a tenant is known and is
    the one mount built without it."""

    def __init__(
        self,
        *,
        audience: str,
        verifiers: Mapping[str, tuple[Ed25519Verifier, str | None]],
        tenant_scoped: bool = True,
        scopes: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        if any(v.audience != audience for v, _ in verifiers.values()):
            raise ValueError("every service verifier must be bound to this service's audience")
        self.audience = audience
        self.verifiers = dict(verifiers)
        self.tenant_scoped = tenant_scoped
        # Calling service name to the scopes it may hold here; a token listing any other is refused (the caller signs
        # its own token, so only the callee can cap it). The dev key signs for any name and is capped the same way.
        self.scopes = {k: frozenset(v) for k, v in (scopes or {}).items()}

    async def principal(self, authorization: Annotated[str | None, Header()] = None) -> Principal:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise Unauthorized("This route is internal and needs a service token.")
        return self.resolve(token)

    def signs(self, token: str) -> bool:
        """Whether `token` names a kid this service trusts for service tokens."""
        try:
            return str(header_of(token).get("kid", "")) in self.verifiers
        except TokenError:
            return False

    def resolve(self, token: str) -> Principal:
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
        team = claims.get("team_id")
        scopes: list[Any] = claims.get("scopes") or []
        allowed = self.scopes.get(sub.removeprefix("service:"), frozenset())
        if not {str(x) for x in scopes} <= allowed:
            raise _refused()
        return Principal(
            kind="service",
            sub=sub,
            email="",
            name=sub,
            tenant_id=str(tenant or ""),
            team_id=str(team) if team else None,
            team_ids=[str(team)] if team else [],
            roles={},
            scopes=[str(x) for x in scopes],
            auth_method="service",
        )


def mint_service_token(
    signer: Ed25519Signer,
    *,
    service: str,
    audience: str,
    tenant_id: str | None,
    ttl_s: int = 60,
    scopes: list[str] | None = None,
    team_id: str | None = None,
) -> str:
    """A short token one service presents to another, naming the tenant it acts for as a claim; None only for
    introspection, which comes before a tenant is known. `scopes` (`area:action`, checked by ops_access) and `team_id`
    say what it may do and in which team; both are signed, so no query or body can widen them."""
    claims: dict[str, Any] = {"sub": f"service:{service}", "kind": "service", "aud": audience}
    if tenant_id is not None:
        claims["tenant_id"] = tenant_id
    if scopes:
        claims["scopes"] = list(scopes)
    if team_id is not None:
        claims["team_id"] = team_id
    return mint(claims, signer, ttl_s=ttl_s)
