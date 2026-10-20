"""OpenID Connect sign-in: the authorization code flow with PKCE (RFC 7636, S256), as a relying party.

`begin` builds the authorization URL and returns the state, nonce and code verifier the caller keeps server-side until
the provider sends the person back. `complete` exchanges the code with that verifier and checks the id_token: its
signature against the issuer's published keys, `iss`, `aud`, `exp`, the nonce, and, for a forced sign-in (a step-up),
that `auth_time` is no older than the flow. Only asymmetric algorithms are accepted, so a token signed with the client
secret or with `none` never passes. The issuer's discovery document must name the configured issuer exactly.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urlencode

import httpx
import jwt

from .identity import SignInRefused, VerifiedIdentity

ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"]


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    client_id: str
    client_secret: str | None = None
    scopes: tuple[str, ...] = ("openid", "email", "profile")
    # The id_token claim that lists the person's groups; None reads none.
    groups_claim: str | None = None


@dataclass(frozen=True)
class OidcStart:
    url: str
    state: str
    nonce: str
    verifier: str


def challenge_of(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


@dataclass
class OidcClient:
    """One provider's relying party. `metadata` caches each issuer's discovery document and key set across clients;
    the caller keeps one dict for the life of the process."""

    config: OidcConfig
    http: httpx.AsyncClient
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    leeway_s: int = 60

    async def _document(self) -> dict[str, Any]:
        issuer = self.config.issuer.rstrip("/")
        doc = self.metadata.get(issuer)
        if doc is None:
            try:
                r = await self.http.get(f"{issuer}/.well-known/openid-configuration")
                r.raise_for_status()
                doc = cast(dict[str, Any], r.json())
            except (httpx.HTTPError, ValueError) as e:
                raise SignInRefused(f"discovery failed: {e}") from e
            if str(doc.get("issuer", "")).rstrip("/") != issuer:
                raise SignInRefused("discovery names another issuer")
            self.metadata[issuer] = doc
        return doc

    async def _keys(self, doc: dict[str, Any], *, refresh: bool) -> jwt.PyJWKSet:
        cached = doc.get("_jwks")
        if cached is None or refresh:
            try:
                r = await self.http.get(str(doc["jwks_uri"]))
                r.raise_for_status()
                cached = r.json()
            except (httpx.HTTPError, ValueError, KeyError) as e:
                raise SignInRefused(f"key set unavailable: {e}") from e
            doc["_jwks"] = cached
        try:
            return jwt.PyJWKSet.from_dict(cached)
        except jwt.PyJWTError as e:
            raise SignInRefused(f"key set unreadable: {e}") from e

    async def begin(self, *, redirect_uri: str, login_hint: str | None = None, force: bool = False) -> OidcStart:
        doc = await self._document()
        state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.config.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge_of(verifier),
            "code_challenge_method": "S256",
        }
        if login_hint:
            params["login_hint"] = login_hint
        if force:
            # The provider must ask for credentials again; its own session cookie is not enough for a step-up.
            params |= {"prompt": "login", "max_age": "0"}
        endpoint = str(doc["authorization_endpoint"])
        return OidcStart(f"{endpoint}{'&' if '?' in endpoint else '?'}{urlencode(params)}", state, nonce, verifier)

    async def complete(
        self, *, code: str, verifier: str, nonce: str, redirect_uri: str, fresh_since: int | None = None
    ) -> VerifiedIdentity:
        """`fresh_since` (Unix seconds) is set for a forced sign-in: the id_token's `auth_time` must not be older."""
        doc = await self._document()
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": self.config.client_id,
        }
        secret = self.config.client_secret
        auth = httpx.BasicAuth(self.config.client_id, secret) if secret else httpx.USE_CLIENT_DEFAULT
        try:
            r = await self.http.post(str(doc["token_endpoint"]), data=form, auth=auth)
            r.raise_for_status()
            id_token = str(r.json()["id_token"])
        except (httpx.HTTPError, ValueError, KeyError) as e:
            raise SignInRefused(f"code exchange failed: {e}") from e
        claims = await self._verify(doc, id_token)
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise SignInRefused("nonce does not match")
        auth_time = claims.get("auth_time")
        if fresh_since is not None and (not isinstance(auth_time, int) or auth_time < fresh_since - self.leeway_s):
            raise SignInRefused("the provider did not ask for credentials again")
        email = str(claims.get("email") or "").strip().lower()
        if not email or claims.get("email_verified") is False:
            raise SignInRefused("no verified email")
        raw = claims.get(self.config.groups_claim) if self.config.groups_claim else None
        groups = cast(list[Any], raw) if isinstance(raw, list) else [raw] if isinstance(raw, str) else []
        return VerifiedIdentity(
            subject=str(claims["sub"]),
            email=email,
            name=str(claims.get("name") or email),
            auth_time=auth_time if isinstance(auth_time, int) else None,
            groups=tuple(str(g) for g in groups),
        )

    async def _verify(self, doc: dict[str, Any], id_token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as e:
            raise SignInRefused(f"id_token unreadable: {e}") from e
        if header.get("alg") not in ALGORITHMS:
            raise SignInRefused(f"algorithm {header.get('alg')} is not accepted")
        kid = header.get("kid")
        key = None
        for refresh in (False, True):
            keys = await self._keys(doc, refresh=refresh)
            key = next((k for k in keys.keys if kid is None or k.key_id == kid), None)
            if key is not None:
                break
        if key is None:
            raise SignInRefused("no key for the id_token")
        try:
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key=key.key,
                algorithms=[str(header["alg"])],
                audience=self.config.client_id,
                issuer=str(doc["issuer"]),
                leeway=self.leeway_s,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as e:
            raise SignInRefused(f"id_token refused: {e}") from e
        return claims
