"""`POST /oauth/token`: a code for a token (PKCE S256, bound to the client, the redirect and the address), and a
renewal for a new token. A renewal rotates the refresh token, so presenting an old one ends the whole grant, and it
checks the person is still in the address's team before it issues anything: a person who left gets `invalid_grant`
and the connection ends."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..auth import Auth, Issued
from ..store.identity import Grant, IdentityStore, SessionRef
from . import OAuthError, iso
from .authorize import code_hash

REFUSED = OAuthError("invalid_grant", "That grant is not valid. Connect the assistant again.")


def challenge_of(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


@dataclass
class Tokens:
    store: IdentityStore
    auth: Auth
    public_url: str | None

    async def _grant(self, token: str) -> tuple[Grant, str]:
        session_id, _, secret = token.partition(".")
        ref = await self.store.session(session_id) if secret and len(token) <= 200 else None
        grant = await self.store.grant(ref) if ref else None
        if grant is None:
            raise REFUSED
        return grant, secret

    def _response(self, issued: Issued) -> dict[str, Any]:
        return {
            "access_token": issued.token,
            "token_type": "Bearer",
            "expires_in": self.auth.token_ttl_s,
            "refresh_token": issued.refresh_token,
        }

    async def exchange(self, form: dict[str, str], *, request_id: str) -> dict[str, Any]:
        grant_type = form.get("grant_type")
        if grant_type == "authorization_code":
            return await self._code(form)
        if grant_type == "refresh_token":
            return await self._renew(form, request_id=request_id)
        raise OAuthError("unsupported_grant_type", "grant_type is authorization_code or refresh_token.")

    async def _code(self, form: dict[str, str]) -> dict[str, Any]:
        code = form.get("code", "")
        grant, _ = await self._grant(code)
        now = datetime.now(UTC)
        if grant.client_id != form.get("client_id") or grant.redirect_uri != form.get("redirect_uri"):
            raise REFUSED
        if (given := form.get("resource")) is not None and given != grant.resource:
            raise OAuthError("invalid_target", "That is not the address this grant was allowed for.")
        verifier = form.get("code_verifier", "")
        if not 43 <= len(verifier) <= 128 or not hmac.compare_digest(
            challenge_of(verifier), grant.code_challenge or ""
        ):
            raise REFUSED
        refresh_secret = secrets.token_urlsafe(32)
        if not await self.store.redeem_code(
            grant, code_hash=code_hash(code), refresh_hash=_hash(refresh_secret), at=iso(now)
        ):
            raise REFUSED
        user = await self.store.user(grant.tenant_id, grant.user_id)
        issued = await self.auth.issue_for_grant(user, grant, f"{grant.id}.{refresh_secret}", now) if user else None
        if issued is None:
            await self.store.end_grant(grant, at=iso(now), by="admin", actor=grant.user_id, request_id="")
            raise REFUSED
        return self._response(issued)

    async def _renew(self, form: dict[str, str], *, request_id: str) -> dict[str, Any]:
        presented = form.get("refresh_token", "")
        grant, secret = await self._grant(presented)
        # A renewal sent with another client's id is refused and leaves the grant alone.
        if grant.client_id != form.get("client_id") or grant.code_used_at is None:
            raise REFUSED
        now = datetime.now(UTC)
        user = await self.store.user(grant.tenant_id, grant.user_id)
        fresh = secrets.token_urlsafe(32)
        issued = await self.auth.issue_for_grant(user, grant, f"{grant.id}.{fresh}", now) if user else None
        if issued is None:
            # The person left the team or lost the right to run its tools: no token, and the grant ends.
            await self.store.end_grant(grant, at=iso(now), by="admin", actor=grant.user_id, request_id=request_id)
            raise REFUSED
        ref = SessionRef(grant.tenant_id, grant.user_id, grant.id)
        rotated = await self.store.rotate(
            ref, presented=_hash(secret), replacement=_hash(fresh), at=iso(now), request_id=request_id, kind="mcp",
            team_id=grant.team_id,
        )  # fmt: skip
        if not rotated:
            raise REFUSED
        return self._response(issued)
