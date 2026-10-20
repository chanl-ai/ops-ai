"""OIDC sign-in, by failure mode (c-188 F3): an id_token from another issuer or audience, a replayed nonce, a token
signed by another key or with a symmetric or no algorithm, an expired token, a step-up on an old login, an unverified
email, and a discovery document that names another issuer. Each answer comes from a provider that serves the token
under test; the happy path runs through the fake identity provider."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from ops_signin import OidcClient, OidcConfig, SignInRefused
from ops_signin.fake_idp import create_app

ISSUER = "https://idp.test/oidc/bank"
CLIENT = "ops-console"
REDIRECT = "https://ops.test/v1/auth/oidc/callback"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem(k: rsa.RSAPrivateKey) -> bytes:
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _claims(nonce: str, **over: Any) -> dict[str, Any]:
    now = int(time.time())
    base = {
        "iss": ISSUER,
        "aud": CLIENT,
        "sub": "s-1",
        "email": "Ana@Bank.test",
        "email_verified": True,
        "nonce": nonce,
        "iat": now,
        "exp": now + 300,
        "auth_time": now,
    }
    return base | over


def provider(make_token: Callable[[str], str], *, issuer: str = ISSUER) -> httpx.AsyncClient:
    """A provider whose token endpoint answers `make_token(nonce)` for the nonce the authorize URL carried."""
    seen: dict[str, str] = {}

    def handle(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": issuer,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                },
            )
        if path.endswith("/jwks"):
            jwk = RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True)
            return httpx.Response(200, json={"keys": [jwk | {"kid": "k1", "alg": "RS256"}]})
        if path.endswith("/token"):
            return httpx.Response(200, json={"id_token": make_token(seen["nonce"])})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    client.event_hooks["request"] = []
    setattr(client, "_seen", seen)  # noqa: B010
    return client


async def sign_in(http: httpx.AsyncClient, *, fresh_since: int | None = None) -> Any:
    oidc = OidcClient(OidcConfig(ISSUER, CLIENT, "secret"), http)
    start = await oidc.begin(redirect_uri=REDIRECT, force=fresh_since is not None)
    getattr(http, "_seen")["nonce"] = start.nonce  # noqa: B009
    return await oidc.complete(
        code="c", verifier=start.verifier, nonce=start.nonce, redirect_uri=REDIRECT, fresh_since=fresh_since
    )


def signed(
    claims: Callable[[str], dict[str, Any]], key: rsa.RSAPrivateKey = KEY, alg: str = "RS256"
) -> Callable[[str], str]:
    return lambda nonce: jwt.encode(claims(nonce), _pem(key), algorithm=alg, headers={"kid": "k1"})


async def test_a_token_this_provider_signed_for_this_client_signs_in() -> None:
    who = await sign_in(provider(signed(_claims)))
    assert (who.subject, who.email) == ("s-1", "ana@bank.test")


REFUSED: dict[str, Callable[[str], str]] = {
    "another issuer": signed(lambda n: _claims(n, iss="https://evil.test/oidc/bank")),
    "another audience": signed(lambda n: _claims(n, aud="someone-else")),
    "a replayed nonce": signed(lambda n: _claims("an-earlier-nonce")),
    "another key": signed(_claims, key=OTHER),
    "expired": signed(lambda n: _claims(n, iat=1_000, exp=2_000)),
    "unverified email": signed(lambda n: _claims(n, email_verified=False)),
    "no email": signed(lambda n: _claims(n, email="")),
    "signed with the client secret": lambda n: jwt.encode(_claims(n), "secret" * 6, algorithm="HS256"),
    "not signed": lambda n: jwt.encode(_claims(n), None, algorithm="none"),  # pyright: ignore[reportArgumentType]
}


@pytest.mark.parametrize("case", list(REFUSED))
async def test_a_token_that_proves_nothing_is_refused(case: str) -> None:
    with pytest.raises(SignInRefused):
        await sign_in(provider(REFUSED[case]))


async def test_a_discovery_document_naming_another_issuer_is_refused() -> None:
    with pytest.raises(SignInRefused, match="another issuer"):
        await sign_in(provider(signed(_claims), issuer="https://evil.test"))


async def test_a_forced_sign_in_refuses_an_old_login_and_takes_a_fresh_one() -> None:
    started = int(time.time())
    with pytest.raises(SignInRefused, match="again"):
        await sign_in(provider(signed(lambda n: _claims(n, auth_time=started - 3600))), fresh_since=started)
    who = await sign_in(provider(signed(lambda n: _claims(n, auth_time=started))), fresh_since=started)
    assert who.auth_time == started


async def test_the_fake_provider_signs_in_with_pkce_and_asks_again_when_forced() -> None:
    base = "http://idp.test"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(base)), base_url=base) as http:
        oidc = OidcClient(OidcConfig(f"{base}/oidc/bank", CLIENT, "secret"), http)
        start = await oidc.begin(redirect_uri=REDIRECT, login_hint="bo@bank.test", force=True)
        assert "code_challenge_method=S256" in start.url and "prompt=login" in start.url
        code = re.search(r"code=([^&]+)", (await http.get(start.url)).headers["location"])
        assert code is not None
        who = await oidc.complete(
            code=code.group(1),
            verifier=start.verifier,
            nonce=start.nonce,
            redirect_uri=REDIRECT,
            fresh_since=int(time.time()) - 5,
        )
        assert who.email == "bo@bank.test"
        # The verifier is single use at the provider: the same code with another verifier is refused.
        start2 = await oidc.begin(redirect_uri=REDIRECT, login_hint="bo@bank.test")
        code2 = re.search(r"code=([^&]+)", (await http.get(start2.url)).headers["location"])
        assert code2 is not None
        with pytest.raises(SignInRefused, match="exchange"):
            await oidc.complete(code=code2.group(1), verifier=start.verifier, nonce=start2.nonce, redirect_uri=REDIRECT)


async def test_groups_are_read_from_the_named_claim_only() -> None:
    def token(n: str) -> str:
        return jwt.encode(
            _claims(n, groups=["tellers", "branch-12"]), _pem(KEY), algorithm="RS256", headers={"kid": "k1"}
        )

    http = provider(token)
    oidc = OidcClient(OidcConfig(ISSUER, CLIENT, "secret", groups_claim="groups"), http)
    start = await oidc.begin(redirect_uri=REDIRECT)
    getattr(http, "_seen")["nonce"] = start.nonce  # noqa: B009
    who = await oidc.complete(code="c", verifier=start.verifier, nonce=start.nonce, redirect_uri=REDIRECT)
    assert who.groups == ("tellers", "branch-12")
    unnamed = await sign_in(provider(token))
    assert unnamed.groups == ()
