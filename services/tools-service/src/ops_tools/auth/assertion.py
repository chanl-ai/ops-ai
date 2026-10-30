"""A JWT signed with a connection's private key (RFC 7523, c-583): the client assertion a system takes in place of a
client secret (Microsoft Entra apps at banks), and the grant a service account signs in with (DocuSign, Google).

Signed with `cryptography`, already a dependency: RS256 for an RSA key and ES256 for a P-256 key cover the systems
plugins reach, and any other key is refused by name. The header carries the signing certificate's SHA-256 thumbprint
(`x5t#S256`), which Entra reads to find the key. The claims the system checks (`iss`, `sub`, `aud`, `iat`, `nbf`,
`exp`, `jti`) are set here and cannot be replaced by a caller's extra claims, the lifetime is five minutes, and every
assertion has its own id, so a captured one cannot be sent again as new."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

LIFETIME = timedelta(minutes=5)
EXPIRES_SOON = timedelta(days=30)
CHECKED = ("iss", "sub", "aud", "iat", "nbf", "exp", "jti")


class SigningError(ValueError):
    """A key or certificate that cannot sign, named without its value."""


@dataclass(frozen=True)
class CertificateInfo:
    """What a read shows of a signing certificate: never its key."""

    thumbprint: str
    subject: str
    not_after: datetime

    def expired(self, now: datetime) -> bool:
        return now >= self.not_after

    def expires_soon(self, now: datetime) -> bool:
        return now + EXPIRES_SOON >= self.not_after

    def view(self, now: datetime) -> dict[str, Any]:
        return {
            "thumbprint": self.thumbprint,
            "subject": self.subject,
            "notAfter": self.not_after.isoformat(),
            "expiresSoon": self.expires_soon(now),
        }


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _certificate(pem: str) -> x509.Certificate:
    try:
        return x509.load_pem_x509_certificate(pem.encode())
    except ValueError as e:
        raise SigningError("The signing certificate is not a PEM certificate.") from e


def _key(pem: str) -> PrivateKeyTypes:
    try:
        return serialization.load_pem_private_key(pem.encode(), password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm) as e:
        raise SigningError("The signing key is not a private key in PEM without a password.") from e


def read_certificate(pem: str) -> CertificateInfo:
    cert = _certificate(pem)
    return CertificateInfo(
        thumbprint=hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest(),
        subject=cert.subject.rfc4514_string(),
        not_after=cert.not_valid_after_utc,
    )


def key_matches(key_pem: str, cert_pem: str) -> bool:
    """Whether the private key is the certificate's: their public keys are the same."""
    der = serialization.Encoding.DER
    spki = serialization.PublicFormat.SubjectPublicKeyInfo
    mine = _key(key_pem).public_key().public_bytes(der, spki)
    return mine == _certificate(cert_pem).public_key().public_bytes(der, spki)


def sign(
    key_pem: str,
    *,
    issuer: str,
    subject: str | None,
    audience: str,
    cert_pem: str | None = None,
    key_id: str | None = None,
    extra: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> str:
    """A compact JWT. `subject` None leaves `sub` out (a Google service account's grant has none); `extra` adds claims
    such as Google's `scope`, never one of the checked ones."""
    key = _key(key_pem)
    if isinstance(key, rsa.RSAPrivateKey):
        alg = "RS256"
    elif isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256R1):
        alg = "ES256"
    else:
        raise SigningError("The signing key must be RSA or P-256.")
    header: dict[str, Any] = {"alg": alg, "typ": "JWT"}
    if cert_pem:
        der = _certificate(cert_pem).public_bytes(serialization.Encoding.DER)
        header["x5t#S256"] = _b64(hashlib.sha256(der).digest())
    if key_id:
        header["kid"] = key_id
    at = int((now or datetime.now(UTC)).timestamp())
    claims: dict[str, Any] = {k: v for k, v in (extra or {}).items() if k not in CHECKED}
    claims |= {"iss": issuer, "aud": audience, "iat": at, "nbf": at, "exp": at + int(LIFETIME.total_seconds())}
    claims["jti"] = uuid.uuid4().hex
    if subject is not None:
        claims["sub"] = subject
    compact = (_b64(json.dumps(part, separators=(",", ":")).encode()) for part in (header, claims))
    signed = ".".join(compact).encode()
    if isinstance(key, rsa.RSAPrivateKey):
        signature = key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
    else:
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        # JWS wants ES256's signature as r and s side by side (RFC 7518 3.4), not the DER cryptography returns.
        r, s = decode_dss_signature(key.sign(signed, ec.ECDSA(hashes.SHA256())))
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{signed.decode()}.{_b64(signature)}"
