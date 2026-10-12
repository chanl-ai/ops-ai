"""Sign-in, renewal, sign-out and API-key introspection: the decisions, with storage behind `IdentityStore`.

A platform token is short-lived (15 minutes) and names every service it may be presented to in `aud`; the session
behind it lives 8 hours and is renewed only by its opaque refresh token, `<session id>.<secret>`, never by the token
itself. The session id in the refresh token is what lets a reused, already-rotated token be traced to its session
and end it. Every refusal is the same 401, whatever the reason, so a caller learns nothing about which part failed,
and no secret or part of one reaches a log.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ops_policy import Ed25519Signer, TokenError, mint, verify
from ops_service_kit.errors import Unauthorized
from ops_service_kit.ids import new_id

from .store.identity import IdentityStore, SessionRef, User

AUDIENCE = "platform"
KEY_PREFIX = "ok_"


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _refused() -> Unauthorized:
    return Unauthorized("Sign in again.")


@dataclass(frozen=True)
class Issued:
    token: str
    refresh_token: str
    expires_at: str
    principal: dict[str, Any]


@dataclass
class Auth:
    store: IdentityStore
    signer: Ed25519Signer
    # Dev mode's one password for every seeded person; None closes password sign-in (outside dev, until SSO lands).
    demo_password: str | None
    audiences: list[str]
    token_ttl_s: int = 900
    session_ttl_s: int = 8 * 3600

    async def sign_in(self, email: str, password: str, *, request_id: str) -> Issued:
        if self.demo_password is None or not hmac.compare_digest(password.encode(), self.demo_password.encode()):
            raise _refused()
        found = await self.store.users_by_email(email)
        # The same address in two tenants: sign-in names no tenant (I1), so it refuses rather than picking one.
        if len(found) != 1:
            raise _refused()
        return await self.start_session(found[0], request_id=request_id)

    async def start_session(self, user: User, *, request_id: str) -> Issued:
        """A new session and its first token, for sign-in and for an accepted invite."""
        now = datetime.now(UTC)
        session_id, secret = new_id("ses"), secrets.token_urlsafe(32)
        await self.store.open_session(
            user,
            session_id=session_id,
            auth_method="dev",
            refresh_hash=_hash(secret),
            expires_at=_iso(now + timedelta(seconds=self.session_ttl_s)),
            at=_iso(now),
            request_id=request_id,
        )
        return await self._issue(user, session_id, f"{session_id}.{secret}", "dev", now)

    async def refresh(self, refresh_token: str, *, request_id: str) -> Issued:
        session_id, _, secret = refresh_token.partition(".")
        ref = await self.store.session(session_id) if secret else None
        if ref is None:
            raise _refused()
        now = datetime.now(UTC)
        fresh = secrets.token_urlsafe(32)
        rotated = await self.store.rotate(
            ref, presented=_hash(secret), replacement=_hash(fresh), at=_iso(now), request_id=request_id
        )
        user = await self.store.user(ref.tenant_id, ref.user_id) if rotated else None
        if user is None:
            raise _refused()
        return await self._issue(user, ref.id, f"{ref.id}.{fresh}", "dev", now)

    async def session_of(self, token: str) -> tuple[SessionRef, dict[str, Any]]:
        """The live session behind a token this service issued; a signed-out session is refused at once."""
        try:
            claims = verify(token, self.signer.verifier(AUDIENCE))
        except TokenError as e:
            raise _refused() from e
        ref = SessionRef(str(claims.get("tenant_id")), str(claims.get("sub")), str(claims.get("sid")))
        if not await self.store.touch(ref, at=_iso(datetime.now(UTC))):
            raise _refused()
        return ref, claims

    async def sign_out(self, token: str, *, request_id: str) -> None:
        ref, _ = await self.session_of(token)
        await self.store.sign_out(ref, at=_iso(datetime.now(UTC)), request_id=request_id)

    async def _issue(self, user: User, session_id: str, refresh_token: str, method: str, now: datetime) -> Issued:
        roles = await self.store.roles(user.tenant_id, user.id)
        claims = {
            "sub": user.id,
            "sid": session_id,
            "email": user.email,
            "name": user.name,
            "tenant_id": user.tenant_id,
            "team_ids": list(roles),
            "roles": roles,
            "kind": "person",
            "auth_method": method,
            "aud": [AUDIENCE, *(a for a in self.audiences if a != AUDIENCE)],
            "amr": [],
            "auth_time": int(now.timestamp()),
        }
        token = mint(claims, self.signer, ttl_s=self.token_ttl_s, now=now.timestamp())
        return Issued(
            token=token,
            refresh_token=refresh_token,
            expires_at=_iso(now + timedelta(seconds=self.token_ttl_s)),
            principal=principal_from_claims(claims),
        )


@dataclass
class Keys:
    """API-key introspection, for the internal app; it needs no signing key."""

    store: IdentityStore

    async def introspect(self, api_key: str) -> dict[str, Any]:
        """`ok_<id>.<secret>` to the key's principal. The secret is compared by hash in constant time (I11)."""
        key_id, _, secret = api_key.removeprefix(KEY_PREFIX).partition(".")
        if not api_key.startswith(KEY_PREFIX) or not secret:
            raise _refused()
        key = await self.store.key(key_id)
        if key is None or not hmac.compare_digest(_hash(secret), key.secret_hash) or not key.usable:
            raise _refused()
        creator = await self.store.user(key.tenant_id, key.created_by)
        if creator is None:
            raise _refused()
        await self.store.key_used(key, at=_iso(datetime.now(UTC)))
        return principal(
            kind="api_key",
            user=creator,
            team_id=key.team_id,
            roles={},
            scopes=key.scopes,
            auth_method="api_key",
        ) | {"teamIds": [key.team_id]}


def principal(
    *, kind: str, user: User, team_id: str | None, roles: dict[str, str], scopes: list[str], auth_method: str
) -> dict[str, Any]:
    return {
        "kind": kind,
        "sub": user.id,
        "email": user.email,
        "name": user.name,
        "tenantId": user.tenant_id,
        "teamId": team_id,
        "teamIds": list(roles),
        "roles": roles,
        "scopes": scopes,
        "authMethod": auth_method,
    }


def principal_from_claims(claims: dict[str, Any]) -> dict[str, Any]:
    raw_roles: dict[str, Any] = claims.get("roles") or {}
    raw_teams: list[Any] = claims.get("team_ids") or []
    roles = {str(k): str(v) for k, v in raw_roles.items()}
    teams = [str(t) for t in raw_teams]
    user = User(str(claims["tenant_id"]), str(claims["sub"]), str(claims.get("email", "")), str(claims.get("name", "")))
    return principal(
        kind=str(claims.get("kind", "person")),
        user=user,
        team_id=teams[0] if len(teams) == 1 else None,
        roles=roles,
        scopes=[],
        auth_method=str(claims.get("auth_method", "")),
    )
