"""Asymmetric tokens (Ed25519), by failure mode: a token from another key passes, a service holding only the public key
mints a token that passes, a token for another audience passes, and an algorithm swap (HS256 keyed with the public key)
passes."""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from ops_policy import Ed25519Signer, Ed25519Verifier, HmacSigner, TokenError, header_of, mint, verify

T0 = 1_000_000.0


def test_a_public_key_verifies_what_the_private_key_signed() -> None:
    issuer = Ed25519Signer.generate("k1")
    token = mint({"sub": "u1", "aud": "agents"}, issuer, ttl_s=60, now=T0)
    assert header_of(token) == {"alg": "EdDSA", "kid": "k1", "typ": "JWT"}
    verifier = Ed25519Verifier.from_jwk(issuer.public_jwk(), "agents")
    assert verify(token, verifier, now=T0, audience="agents")["sub"] == "u1"


def test_a_holder_of_the_public_key_cannot_mint() -> None:
    verifier = Ed25519Signer.generate("k1").verifier("agents")
    with pytest.raises(TokenError) as e:
        mint({"sub": "u1"}, verifier, ttl_s=60, now=T0)
    assert e.value.reason == "cannot_sign"


def test_a_list_audience_names_the_service() -> None:
    issuer = Ed25519Signer.generate("k1")
    token = mint({"sub": "u1", "aud": ["agents", "tools"]}, issuer, ttl_s=60, now=T0)
    assert verify(token, issuer.verifier("tools"), now=T0)["sub"] == "u1"


def test_the_private_key_round_trips_through_settings_text() -> None:
    issuer = Ed25519Signer.generate("k1")
    again = Ed25519Signer.from_private_text(issuer.private_text(), "k1")
    token = mint({"sub": "u1", "aud": "agents"}, again, ttl_s=60, now=T0)
    assert verify(token, issuer.verifier("agents"), now=T0)["sub"] == "u1"


def test_the_jwk_has_no_private_part() -> None:
    jwk = Ed25519Signer.generate("k1").public_jwk()
    assert set(jwk) == {"kty", "crv", "x", "kid", "alg", "use"}
    assert "d" not in jwk  # the private scalar of an OKP key
    assert len(base64.urlsafe_b64decode(jwk["x"] + "=")) == 32


def test_hmac_still_works_unchanged() -> None:
    signer = HmacSigner(hmac.new(b"secret", b"purpose", hashlib.sha256).digest())
    token = mint({"sub": "u1"}, signer, ttl_s=60, now=T0)
    assert verify(token, signer, now=T0)["sub"] == "u1"
    assert "kid" not in header_of(token)


ISSUER = Ed25519Signer.generate("k1")
AGENTS = {"sub": "u1", "aud": "agents"}
# The classic algorithm swap: sign HS256 with the public key bytes and hope the verifier uses them as a secret.
PUBLIC_AS_SECRET = HmacSigner(base64.urlsafe_b64decode(ISSUER.public_jwk()["x"] + "=="))


@pytest.mark.parametrize(
    ("claims", "signer", "verifier", "audience", "why"),
    [
        (AGENTS, Ed25519Signer.generate("k1"), ISSUER.verifier("agents"), None, "signature"),
        ({"sub": "attacker", "aud": "agents"}, PUBLIC_AS_SECRET, ISSUER.verifier("agents"), None, "algorithm"),
        ({"sub": "u1", "aud": "tools"}, ISSUER, ISSUER.verifier("agents"), None, "audience"),
        ({"sub": "u1"}, ISSUER, ISSUER.verifier("agents"), None, "audience"),
        # A verify that names no audience, and a call that tries to widen a verifier bound to another one.
        (AGENTS, ISSUER, ISSUER, None, "audience"),
        (AGENTS, ISSUER, ISSUER.verifier("tools"), "agents", "audience"),
    ],
    ids=["another-key", "hs256-with-public-key", "another-audience", "no-audience-claim", "unbound", "widened"],
)
def test_a_token_that_proves_nothing_is_refused(
    claims: dict[str, str],
    signer: Ed25519Signer | HmacSigner,
    verifier: Ed25519Signer | Ed25519Verifier,
    audience: str | None,
    why: str,
) -> None:
    token = mint(claims, signer, ttl_s=60, now=T0)
    with pytest.raises(TokenError) as e:
        verify(token, verifier, now=T0, audience=audience)
    assert e.value.reason == why
