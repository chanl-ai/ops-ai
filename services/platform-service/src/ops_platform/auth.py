"""Sign-in, renewal, sign-out and API-key introspection: the decisions, with storage behind `IdentityStore`.

A platform token is short-lived (15 minutes) and names every service it may be presented to in `aud`; the session behind
it lives 8 hours and is renewed only by its opaque refresh token, `<session id>.<secret>`, never by the token itself.
The token's `access` names, per team, the role ids the person holds there and `perm_version` the tenant's permission
version when it was issued; ops_access decides from them with no call back here, caching role grids under the version.
The session id in the refresh token is what lets a reused, already-rotated token be traced to its session and end it.
Every refusal is the same 401, whatever the reason, so a caller learns nothing about which part failed, and no secret or
part of one reaches a log.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ops_policy import STEP_UP_TTL_S, Ed25519Signer, TokenError, mint, verify
from ops_service_kit.errors import Unauthorized
from ops_service_kit.ids import new_id

from .passwords import Passwords
from .store.identity import IdentityStore, SessionRef, User
from .store.policies import PolicyStore
from .store.workspace import WorkspaceStore

AUDIENCE = "platform"
KEY_PREFIX = "ok_"
# A step-up's `kind`: ops_identity refuses it as a session (only "person" resolves), and its `typ` is what
# ops_policy.verify_step_up checks, so neither token passes as the other.
STEP_UP_KIND = "step_up"
STEP_UP_TYPE = "step_up"


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


@dataclass(frozen=True)
class StepUpIssued:
    token: str
    expires_at: str


# The methods an SSO session has; its step-up goes back to its identity provider, never to a password.
SSO_METHODS = frozenset({"oidc", "saml"})


@dataclass
class Auth:
    store: IdentityStore
    signer: Ed25519Signer
    passwords: Passwords
    audiences: list[str]
    token_ttl_s: int = 900
    session_ttl_s: int = 8 * 3600
    step_up_ttl_s: int = STEP_UP_TTL_S
    # The workspace's security team for the token (c-202); unset in tests that build Auth by hand.
    workspace: WorkspaceStore | None = None

    async def sign_in(self, email: str, password: str, *, request_id: str) -> Issued:
        # Wrong passwords are counted per address before anything says whether it has an account (c-196), so an
        # unknown address gets the same 401s and then the same 429 as a known one.
        await self.passwords.screen_email(email, password)
        found = await self.store.users_by_email(email)
        # The same address in two tenants: sign-in names no tenant (I1), so it refuses rather than picking one.
        if len(found) != 1:
            await self.passwords.refuse_unknown(password)
            await self.passwords.count_email_failure(email)
            raise _refused()
        method = await self.passwords.check(found[0], password, request_id=request_id)
        if method is None:
            await self.passwords.count_email_failure(email)
            raise _refused()
        await self.passwords.clear_email_failures(email)
        return await self.start_session(found[0], request_id=request_id, method=method)

    async def start_session(
        self, user: User, *, request_id: str, method: str, provider_id: str | None = None
    ) -> Issued:
        """A new session and its first token, for sign-in, an SSO sign-in and an accepted invite. `method` is how
        the person proved who they are (dev, password, oidc, saml); every token of the session carries it."""
        now = datetime.now(UTC)
        session_id, secret = new_id("ses"), secrets.token_urlsafe(32)
        await self.store.open_session(
            user,
            session_id=session_id,
            auth_method=method,
            refresh_hash=_hash(secret),
            expires_at=_iso(now + timedelta(seconds=self.session_ttl_s)),
            at=_iso(now),
            request_id=request_id,
            provider_id=provider_id,
        )
        return await self._issue(user, session_id, f"{session_id}.{secret}", method, now)

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
        method = await self.store.method(ref) if user else None
        if user is None or method is None:
            raise _refused()
        return await self._issue(user, ref.id, f"{ref.id}.{fresh}", method.auth_method, now)

    async def session_of(self, token: str) -> tuple[SessionRef, dict[str, Any]]:
        """The live session behind a token this service issued; a signed-out session is refused at once."""
        try:
            claims = verify(token, self.signer.verifier(AUDIENCE))
        except TokenError as e:
            raise _refused() from e
        # A step-up names the same session but is not one: only a person's token opens the session behind it.
        if claims.get("kind", "person") != "person":
            raise _refused()
        ref = SessionRef(str(claims.get("tenant_id")), str(claims.get("sub")), str(claims.get("sid")))
        if not await self.store.touch(ref, at=_iso(datetime.now(UTC))):
            raise _refused()
        return ref, claims

    async def sign_out(self, token: str, *, request_id: str) -> None:
        ref, _ = await self.session_of(token)
        await self.store.sign_out(ref, at=_iso(datetime.now(UTC)), request_id=request_id)

    async def step_up(self, token: str, password: str, *, request_id: str) -> StepUpIssued:
        """A short-lived proof that the signed-in person re-entered their password. A wrong password is told apart from
        a dead session: the caller is already signed in, so the message hides nothing. An SSO session is refused here
        with `wrong_method`: it steps up at its own identity provider."""
        ref, _ = await self.session_of(token)
        method = await self.store.method(ref)
        if method is not None and method.auth_method in SSO_METHODS:
            raise Unauthorized("Confirm it is you with your company sign-in.", code="wrong_method")
        user = await self.store.user(ref.tenant_id, ref.user_id)
        if user is None or method is None:
            raise _refused()
        if await self.passwords.check(user, password, request_id=request_id) is None:
            raise Unauthorized("That password is not right.", code="wrong_password")
        return await self.mint_step_up(ref, user, method=method.auth_method, request_id=request_id)

    async def mint_step_up(self, ref: SessionRef, user: User, *, method: str, request_id: str) -> StepUpIssued:
        """Signed with the same key as the session token, so every service verifies it through the published key
        set. It names the person by `sub` and `email` and carries the session's `aud`; a service compares the subject
        to the person deciding."""
        now = datetime.now(UTC)
        claims = {
            "sub": user.id,
            "sid": ref.id,
            "email": user.email,
            "tenant_id": user.tenant_id,
            "kind": STEP_UP_KIND,
            "typ": STEP_UP_TYPE,
            # Unique per token: two minted in the same second are otherwise byte for byte the same.
            "jti": new_id("tok"),
            "aud": [AUDIENCE, *(a for a in self.audiences if a != AUDIENCE)],
        }
        minted = mint(claims, self.signer, ttl_s=self.step_up_ttl_s, now=now.timestamp())
        await self.store.step_up(ref, at=_iso(now), request_id=request_id, method=method)
        return StepUpIssued(token=minted, expires_at=_iso(now + timedelta(seconds=self.step_up_ttl_s)))

    async def _issue(self, user: User, session_id: str, refresh_token: str, method: str, now: datetime) -> Issued:
        roles = await self.store.roles(user.tenant_id, user.id)
        version = await self.store.permission_version(user.tenant_id)
        access = await self.store.access(user.tenant_id, user.id, now=_iso(now))
        policies = await PolicyStore(self.store.db).token_values(user.tenant_id)
        claims = {
            "sub": user.id,
            "sid": session_id,
            "email": user.email,
            "name": user.name,
            "tenant_id": user.tenant_id,
            "team_ids": await self.store.acting_teams(user.tenant_id, user.id, now=_iso(now)),
            # Which team holds the Security-team actions in this workspace (c-202), for ops_access.
            **({"security_team": await self.workspace.security_team(user.tenant_id)} if self.workspace else {}),
            "roles": roles,
            "perm_version": version,
            "access": access,
            "policies": policies,
            "kind": "person",
            "auth_method": method,
            # Unique per token: a refresh in the same second as the last one would otherwise repeat it exactly.
            "jti": new_id("tok"),
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
        target = await self.store.key_used(key, at=_iso(datetime.now(UTC)))
        return principal(
            kind="api_key",
            user=creator,
            team_id=key.team_id,
            roles={},
            scopes=key.scopes,
            auth_method="api_key",
        ) | {
            "teamIds": [key.team_id],
            "policies": await PolicyStore(self.store.db).token_values(key.tenant_id),
            # Which key, and what it may start: agents-service records `key:<id>` as a run's starter and refuses
            # anything outside the target.
            "apiKey": {"id": key.id, "target": target},
        }


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
    ) | {
        # The token's teams, which for a workspace admin include teams they hold no membership in (c-208).
        "teamIds": teams,
        "policies": dict(claims.get("policies") or {}),
    }
