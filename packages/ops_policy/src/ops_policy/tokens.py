"""Signed tokens with an expiry, as compact JWTs, behind a `Signer` a KMS adapter can replace.

`HmacSigner` (HS256) signs approval and step-up tokens: one shared secret signs and verifies. `Ed25519Signer` signs
identity tokens: only the issuer holds the private key, and every other service verifies with `Ed25519Verifier`, built
from the public key the issuer publishes as a JWK, so a service that verifies can never mint. The format stays a JWT
because OPA verifies approval tokens with its built-in `io.jwt.decode_verify`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class TokenError(ValueError):
    """Why a token was refused. `reason` is one of: malformed, algorithm, signature, expired, not_yet_valid, audience,
    type, subject, too_old, cannot_sign."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class Signer(Protocol):
    @property
    def algorithm(self) -> str: ...

    def sign(self, message: bytes) -> bytes: ...

    def verify(self, message: bytes, signature: bytes) -> bool: ...


@dataclass(frozen=True)
class HmacSigner:
    """HS256 over a shared secret. Whoever can verify can also mint, which is why production needs a KMS signer."""

    key: bytes
    algorithm: str = "HS256"

    @classmethod
    def derived(cls, secret: str, purpose: str) -> HmacSigner:
        """A key for one purpose only, so a token minted for one use never verifies as another."""
        return cls(hmac.new(secret.encode(), purpose.encode(), hashlib.sha256).digest())

    def sign(self, message: bytes) -> bytes:
        return hmac.new(self.key, message, hashlib.sha256).digest()

    def verify(self, message: bytes, signature: bytes) -> bool:
        return hmac.compare_digest(self.sign(message), signature)


@dataclass(frozen=True)
class Ed25519Verifier:
    """Verifies EdDSA tokens with a public key; it has no private key, so it cannot mint. `audience` is the service
    holding it: bound here rather than passed per call, so no verify through this verifier can skip the `aud` check
    and accept a token issued for another service (I14)."""

    key: Ed25519PublicKey
    kid: str
    audience: str
    algorithm: str = "EdDSA"

    @classmethod
    def from_jwk(cls, jwk: dict[str, Any], audience: str) -> Ed25519Verifier:
        if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519" or not isinstance(jwk.get("x"), str):
            raise TokenError("malformed", "The key is not an Ed25519 public key.")
        return cls(Ed25519PublicKey.from_public_bytes(_unb64(jwk["x"])), str(jwk.get("kid", "")), audience)

    def sign(self, message: bytes) -> bytes:
        raise TokenError("cannot_sign", "A public key verifies tokens; it cannot sign them.")

    def verify(self, message: bytes, signature: bytes) -> bool:
        try:
            self.key.verify(signature, message)
        except InvalidSignature:
            return False
        return True

    def public_jwk(self) -> dict[str, str]:
        raw = self.key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return {"kty": "OKP", "crv": "Ed25519", "x": _b64(raw), "kid": self.kid, "alg": self.algorithm, "use": "sig"}


@dataclass(frozen=True)
class Ed25519Signer:
    """Signs EdDSA tokens with a private key; `kid` names the key in each token header so verifiers can pick it out
    of the published key set during a rotation."""

    key: Ed25519PrivateKey
    kid: str
    algorithm: str = "EdDSA"

    @classmethod
    def generate(cls, kid: str) -> Ed25519Signer:
        return cls(Ed25519PrivateKey.generate(), kid)

    @classmethod
    def from_private_text(cls, text: str, kid: str) -> Ed25519Signer:
        """From the base64url text of the 32-byte private key, as a secret manager holds it."""
        return cls(Ed25519PrivateKey.from_private_bytes(_unb64(text.strip())), kid)

    def private_text(self) -> str:
        raw = self.key.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
        )
        return _b64(raw)

    def verifier(self, audience: str) -> Ed25519Verifier:
        return Ed25519Verifier(self.key.public_key(), self.kid, audience)

    def public_jwk(self) -> dict[str, str]:
        return self.verifier("").public_jwk()

    def sign(self, message: bytes) -> bytes:
        return self.key.sign(message)

    def verify(self, message: bytes, signature: bytes) -> bool:
        try:
            self.key.public_key().verify(signature, message)
        except InvalidSignature:
            return False
        return True


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def mint(claims: dict[str, Any], signer: Signer, *, ttl_s: int, now: float | None = None) -> str:
    """Signs `claims` plus `iat` and `exp`."""
    issued = int(now if now is not None else time.time())
    body = {**claims, "iat": issued, "exp": issued + ttl_s}
    head: dict[str, str] = {"alg": signer.algorithm, "typ": "JWT"}
    kid = getattr(signer, "kid", None)
    if isinstance(kid, str) and kid:
        head["kid"] = kid
    header = _b64(json.dumps(head, separators=(",", ":"), sort_keys=True).encode())
    payload = _b64(json.dumps(body, separators=(",", ":"), sort_keys=True).encode())
    signature = signer.sign(f"{header}.{payload}".encode())
    return f"{header}.{payload}.{_b64(signature)}"


# Slack on `iat` only: a clock stepped back (macOS steps it on wake) puts a fresh token a second or two in the future.
# Expiry stays exact.
ISSUED_SKEW_S = 5


def verify(
    token: str, signer: Signer, *, now: float | None = None, leeway_s: int = 0, audience: str | None = None
) -> dict[str, Any]:
    """The claims of a token this signer issued that has not expired; raises TokenError otherwise. With an audience,
    the token's `aud` (a string or a list) must name it: a token issued for one service is refused by every other.
    EdDSA tokens are platform identities, so for them an audience is required: the verifier's bound one, or
    `audience` when verifying with the private key. HMAC approval and step-up tokens keep it optional."""
    bound = getattr(signer, "audience", None)
    if isinstance(bound, str) and bound:
        if audience is not None and audience != bound:
            raise TokenError("audience", f"This verifier is bound to {bound}, not {audience}.")
        audience = bound
    if audience is None and signer.algorithm == "EdDSA":
        raise TokenError("audience", "An EdDSA token is verified only for a named audience.")
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenError("malformed", "The token is not a signed token.")
    try:
        header = json.loads(_unb64(parts[0]))
        claims = json.loads(_unb64(parts[1]))
        signature = _unb64(parts[2])
    except ValueError as e:
        raise TokenError("malformed", "The token could not be read.") from e
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise TokenError("malformed", "The token could not be read.")
    if cast(dict[str, Any], header).get("alg") != signer.algorithm:
        # Checked before the signature: a token claiming `none` or another algorithm is never verified as this one.
        raise TokenError("algorithm", "The token is signed with an algorithm this service does not accept.")
    if not signer.verify(f"{parts[0]}.{parts[1]}".encode(), signature):
        raise TokenError("signature", "The token's signature does not match.")
    body = cast(dict[str, Any], claims)
    t = now if now is not None else time.time()
    exp, iat = body.get("exp"), body.get("iat")
    if not isinstance(exp, int) or not isinstance(iat, int):
        raise TokenError("malformed", "The token has no issue or expiry time.")
    if t > exp + leeway_s:
        raise TokenError("expired", "The token has expired.")
    if t + max(leeway_s, ISSUED_SKEW_S) < iat:
        raise TokenError("not_yet_valid", "The token was issued in the future.")
    if audience is not None:
        aud = body.get("aud")
        named = aud == audience or (isinstance(aud, list) and audience in cast(list[Any], aud))
        if not named:
            raise TokenError("audience", f"The token was not issued for {audience}.")
    return body


def header_of(token: str) -> dict[str, Any]:
    """The header without verifying it: a verifier reads `kid` here to choose the key, then verifies with it."""
    try:
        head = json.loads(_unb64(token.split(".", maxsplit=1)[0]))
    except (ValueError, IndexError) as e:
        raise TokenError("malformed", "The token could not be read.") from e
    if not isinstance(head, dict):
        raise TokenError("malformed", "The token could not be read.")
    return cast(dict[str, Any], head)


def claims_of(token: str) -> dict[str, Any]:
    """The payload without verifying it, for logs and tests only."""
    return json.loads(_unb64(token.split(".")[1]))
