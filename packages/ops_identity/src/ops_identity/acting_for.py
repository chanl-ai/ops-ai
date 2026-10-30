"""Whom a service's call acts for (c-558), proven by a token platform-service signs, never by a field in the body.

agents-service gets one per (person, team) from platform-service's internal `POST /v1/acting-for-tokens`, which checks
the person is a member of the team, and sends it on each tools call as `X-Acting-For`, beside its own service token.
tools-service verifies it with `Identity.acting_for`. In dev mode there is no platform-service to ask: the token is
signed with the calling service's own key and accepted only by a service built for dev, so a dev stack runs the same
checks and a platform stack never accepts a token a service signed for itself.

The token is its own `kind`, so it never resolves as a session (`Identity._from_token` takes only `person`), and a
session token is refused where an acting-for token is asked for.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ops_policy import Ed25519Signer, mint
from ops_service_kit.errors import Forbidden, ServiceUnavailable

if TYPE_CHECKING:
    from .client import ServiceClient

ACTING_FOR_KIND = "acting_for"
HEADER = "X-Acting-For"
TTL_S = 60
# A cached token is renewed this long before it expires, so one sent never lapses on the way.
RENEW_BEFORE_S = 10


@dataclass(frozen=True)
class ActingForPerson:
    """The person a call acts for, from a verified acting-for token: `sub` is their id (`dev:<email>` in dev)."""

    sub: str
    email: str
    name: str
    team_id: str


def refused(why: str) -> Forbidden:
    return Forbidden(f"The acting-for token is not valid: {why}.", code="acting_for_refused")


def person_of(claims: dict[str, Any], *, service: str, tenant_id: str, team_id: str | None) -> ActingForPerson:
    """The person a verified token's claims name, once they are this service's and this call's."""
    if claims.get("kind") != ACTING_FOR_KIND:
        raise refused("it is not an acting-for token")
    act: dict[str, Any] = claims.get("act") or {}
    if act.get("sub") != service:
        raise refused("it was minted for another service")
    if claims.get("tenant_id") != tenant_id or not team_id or claims.get("team_id") != team_id:
        raise refused("it names another workspace or team than the call")
    return ActingForPerson(
        sub=str(claims["sub"]),
        email=str(claims.get("email", "")),
        name=str(claims.get("name", "")),
        team_id=str(claims["team_id"]),
    )


Mint = Callable[[str, str, str], Awaitable[tuple[str, float]]]


class ActingForTokens:
    """A calling service's acting-for tokens, one per (tenant, person, team), each kept until shortly before it
    expires. When platform-service cannot mint one, a cached token is served until it expires; with none, the call
    answers 503 `acting_for_unavailable`, which a chat shows as "try again", never as "not connected"."""

    def __init__(self, mint_one: Mint, *, clock: Callable[[], float] = time.time) -> None:
        self._mint = mint_one
        self._clock = clock
        self._cache: dict[tuple[str, str, str], tuple[str, float]] = {}

    async def token(self, *, tenant_id: str, email: str, team_id: str) -> str:
        at = (tenant_id, email, team_id)
        now = self._clock()
        held = self._cache.get(at)
        if held is not None and held[1] - RENEW_BEFORE_S > now:
            return held[0]
        try:
            minted = await self._mint(tenant_id, email, team_id)
        except Forbidden:
            raise
        except Exception as e:
            if held is not None and held[1] > now:
                return held[0]
            raise ServiceUnavailable(
                "Whom this call acts for could not be confirmed; try again.", code="acting_for_unavailable"
            ) from e
        self._cache[at] = minted
        return minted[0]

    @classmethod
    def from_platform(cls, platform: ServiceClient) -> ActingForTokens:
        """Minted by platform-service's internal route, through the caller's client for it; the service token names
        the tenant and team (a request body never does)."""

        # Here, not at the top: client imports resolve, which imports this module.
        from .client import ServiceCallError  # noqa: PLC0415

        async def mint_one(tenant_id: str, email: str, team_id: str) -> tuple[str, float]:
            try:
                data = await platform.post("/v1/acting-for-tokens", {"email": email}, tenant=tenant_id, team=team_id)
            except ServiceCallError as e:
                if e.status in (403, 404):
                    raise refused(e.message) from e
                raise
            return str(data["token"]), time.time() + TTL_S

        return cls(mint_one)

    @classmethod
    def for_dev(cls, signer: Ed25519Signer, *, service: str, audience: str = "tools") -> ActingForTokens:
        """Signed with the service's own key, as no platform-service runs in dev; the person is `dev:<email>`, so dev
        people stay apart although they share one dev subject."""

        async def mint_one(tenant_id: str, email: str, team_id: str) -> tuple[str, float]:
            claims = {
                "sub": f"dev:{email}",
                "email": email,
                "name": email,
                "tenant_id": tenant_id,
                "team_id": team_id,
                "kind": ACTING_FOR_KIND,
                "act": {"sub": f"service:{service}"},
                "aud": audience,
            }
            return mint(claims, signer, ttl_s=TTL_S), time.time() + TTL_S

        return cls(mint_one)
