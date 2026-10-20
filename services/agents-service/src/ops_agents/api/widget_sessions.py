"""Widget sessions, origins and rate limits (c-117).

A page on another origin never holds a long-lived key. It gets a session that lasts 15 minutes, signed by
agents-service with a key derived for this one purpose, and bound to the deployment, the page's origin and the person:
minted either from the bank's SSO token the host page passes in, or by the bank's own server with the widget's mint key.
Every widget request must come from the origin the session names, and that origin must still be on the deployment.
"""

from __future__ import annotations

import base64
import json
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit

from ops_access import CHAT_USER
from ops_identity import Principal as Caller
from ops_policy import HmacSigner, TokenError, mint, verify
from ops_service_kit.errors import ApiError, Forbidden, Unauthorized, ValidationFailed

from .auth import Principal
from .deps import Runtime

SESSION_TTL_S = 15 * 60
SESSION_TYPE = "ops-widget-session"
# Messages a minute; past either the request is refused with 429 and a retry hint.
PER_DEPLOYMENT = 60
PER_PERSON = 10


class TooManyRequests(ApiError):
    status = 429
    code = "rate_limited"


@dataclass(frozen=True)
class WidgetSession:
    deployment_id: str
    origin: str
    tenant_id: str
    team_id: str
    email: str
    name: str
    sub: str

    def principal(self) -> Principal:
        """The person as the chat code sees them: in the deployment's team as a Chat user (ops_access), who chats with
        the agent and reads their own threads only, and approving for no team."""
        identity = Caller(
            kind="person",
            sub=self.sub,
            email=self.email,
            name=self.name,
            tenant_id=self.tenant_id,
            team_id=self.team_id,
            team_ids=[self.team_id],
            roles={},
            scopes=[],
            auth_method="session",
            access={self.team_id: [CHAT_USER.id]},
        )
        return Principal(
            name=self.name,
            email=self.email,
            team_id=self.team_id,
            tenant_id=self.tenant_id,
            sub=self.sub,
            team_ids=(self.team_id,),
            identity=identity,
        )


def normal_origin(value: str) -> str:
    """`scheme://host[:port]` exactly, lowercased, with no path; refused when it is anything else or a wildcard."""
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or "*" in value or parts.path not in ("", "/"):
        raise ValidationFailed(f"{value!r} is not an origin like https://intranet.bank.example.")
    if parts.query or parts.fragment or parts.username:
        raise ValidationFailed(f"{value!r} is not an origin like https://intranet.bank.example.")
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{parts.hostname.lower()}{port}"


def _signer(rt: Runtime) -> HmacSigner:
    return HmacSigner.derived(rt.settings.review_key.get_secret_value(), "widget-session")


def mint_session(rt: Runtime, deployment: dict[str, Any], origin: str, person: Principal) -> str:
    claims = {
        "typ": SESSION_TYPE,
        "dep": deployment["id"],
        "origin": origin,
        "tenant": deployment["tenant_id"],
        "team": deployment["team_id"],
        "email": person.email,
        "name": person.name or person.email,
        "sub": person.sub or person.email,
    }
    return mint(claims, _signer(rt), ttl_s=SESSION_TTL_S)


def claimed_tenant(token: str | None) -> str | None:
    """The tenant a session names, read without verifying it. It only chooses which tenant's deployment to load, under
    that tenant's row-level security, so the page's origin can be checked before the session is: an ended session from
    a listed origin then answers 401 the page can read and re-exchange. Every decision after uses the verified session
    and the deployment row (`read_session`)."""
    try:
        part = (token or "").split(".")[1]
        claims: object = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return None
    tenant = cast(dict[str, object], claims).get("tenant") if isinstance(claims, dict) else None
    return tenant if isinstance(tenant, str) and tenant else None


def read_session(rt: Runtime, token: str | None, deployment: dict[str, Any], origin: str | None) -> WidgetSession:
    """The session a widget request carries, refused unless it was minted for this deployment and this origin. The
    tenant and team come from the deployment row, never from the session's claims; claims naming another are refused."""
    if not token:
        raise Unauthorized("This widget has no session; it starts one when it loads.")
    try:
        claims = verify(token, _signer(rt))
    except TokenError as e:
        raise Unauthorized("The widget's session has ended; it starts a new one.") from e
    if claims.get("typ") != SESSION_TYPE or claims.get("dep") != deployment["id"]:
        raise Unauthorized("That session is for another widget.")
    if claims.get("tenant") != deployment["tenant_id"] or claims.get("team") != deployment["team_id"]:
        raise Unauthorized("That session is for another widget.")
    if not origin or normal_origin(origin) != claims.get("origin"):
        raise Forbidden("This widget session belongs to another page.", code="origin_mismatch")
    return WidgetSession(
        deployment_id=str(claims["dep"]),
        origin=str(claims["origin"]),
        tenant_id=str(deployment["tenant_id"]),
        team_id=str(deployment["team_id"]),
        email=str(claims["email"]),
        name=str(claims["name"]),
        sub=str(claims["sub"]),
    )


def allowed(deployment: dict[str, Any], origin: str | None) -> str:
    """The request's origin when the deployment lists it; a request with none (a script or a server) is refused."""
    if not origin:
        raise Forbidden(
            "Widget requests come from a page; servers mint with the widget's mint key.", code="origin_required"
        )
    o = normal_origin(origin)
    if o not in [str(x) for x in deployment["origins"]]:
        raise Forbidden(f"{o} may not use this widget.", code="origin_not_allowed")
    return o


class RateLimit:
    """A sliding minute per deployment and per person, in this process. A multi-process deployment shares it through the
    gateway's limiter later; one process is the MVP's shape (one VM)."""

    def __init__(self, clock: Any = time.monotonic) -> None:
        self._clock = clock
        self._seen: dict[str, deque[float]] = {}

    def hit(self, key: str, limit: int) -> float | None:
        """Counts one request under `key`; the seconds to wait when `limit` were already made this minute."""
        now = self._clock()
        q = self._seen.setdefault(key, deque())
        while q and now - q[0] >= 60:
            q.popleft()
        if len(q) >= limit:
            return 60 - (now - q[0])
        q.append(now)
        return None

    def check(self, deployment_id: str, email: str) -> None:
        for key, limit in ((f"dep:{deployment_id}", PER_DEPLOYMENT), (f"person:{deployment_id}:{email}", PER_PERSON)):
            if (wait := self.hit(key, limit)) is not None:
                raise TooManyRequests(
                    f"Too many messages; try again in {int(wait) + 1} seconds.", details={"retryAfter": int(wait) + 1}
                )
