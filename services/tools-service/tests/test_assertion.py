"""A signed client assertion (RFC 7523) and the certificate it names (c-583), by failure mode: the signature does not
verify with the certificate's public key; the header names no algorithm or the wrong thumbprint, so Entra cannot find
the key; a claim Entra checks is missing, or the lifetime runs past what it accepts; two assertions share an id, so the
second reads as a replay; a key type the platform cannot sign with is used silently; a certificate's expiry or
thumbprint is read wrong; and a key that does not belong to its certificate is taken as matching."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.x509.oid import NameOID

from ops_tools.auth.assertion import SigningError, key_matches, read_certificate, sign

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
TOKEN_URL = "https://login.microsoftonline.test/tenant/oauth2/v2.0/token"


def pair(kind: str = "rsa", *, days: int = 365) -> tuple[str, str, Any]:
    """A key and its self-signed certificate, as PEM, and the key object."""
    key: Any = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if kind == "rsa"
        else (ec.generate_private_key(ec.SECP256R1() if kind == "p256" else ec.SECP384R1()))
    )
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ops-ai-acme")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(days=1))
        .not_valid_after(NOW + timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return key_pem, cert.public_bytes(serialization.Encoding.PEM).decode(), cert


def unb64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def parts(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    head, body, sig = token.split(".")
    return json.loads(unb64(head)), json.loads(unb64(body)), f"{head}.{body}".encode(), unb64(sig)


def test_an_rsa_assertion_verifies_with_the_certificate_and_names_it_by_thumbprint() -> None:
    key_pem, cert_pem, cert = pair()
    token = sign(key_pem, issuer="client-1", subject="client-1", audience=TOKEN_URL, cert_pem=cert_pem, now=NOW)
    header, claims, signed, signature = parts(token)
    cert.public_key().verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    thumb = base64.urlsafe_b64encode(hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).digest())
    assert header == {"alg": "RS256", "typ": "JWT", "x5t#S256": thumb.decode().rstrip("=")}, header
    assert (claims["iss"], claims["sub"], claims["aud"]) == ("client-1", "client-1", TOKEN_URL)
    assert claims["nbf"] <= claims["iat"] == int(NOW.timestamp()) and claims["exp"] - claims["iat"] == 300


def test_each_assertion_has_its_own_id() -> None:
    key_pem, cert_pem, _ = pair()
    ids = {
        parts(sign(key_pem, issuer="c", subject="c", audience=TOKEN_URL, cert_pem=cert_pem))[1]["jti"] for _ in range(5)
    }
    assert len(ids) == 5


def test_a_p256_key_signs_es256_and_a_key_id_is_named() -> None:
    key_pem, cert_pem, cert = pair("p256")
    token = sign(key_pem, issuer="c", subject="u", audience="aud", cert_pem=cert_pem, key_id="k1", now=NOW)
    header, _, signed, signature = parts(token)
    assert header["alg"] == "ES256" and header["kid"] == "k1"
    r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    cert.public_key().verify(encode_dss_signature(r, s), signed, ec.ECDSA(hashes.SHA256()))


def test_extra_claims_go_in_and_cannot_replace_the_checked_ones() -> None:
    key_pem, cert_pem, _ = pair()
    token = sign(
        key_pem, issuer="svc@acme.test", subject=None, audience=TOKEN_URL, cert_pem=cert_pem,
        extra={"scope": "drive.readonly", "aud": "https://elsewhere.test", "exp": 4_000_000_000},
    )  # fmt: skip
    claims = parts(token)[1]
    assert claims["scope"] == "drive.readonly" and claims["aud"] == TOKEN_URL and claims["exp"] - claims["iat"] == 300
    assert "sub" not in claims


def test_a_key_the_platform_cannot_sign_with_is_refused() -> None:
    key_pem, cert_pem, _ = pair("p384")
    with pytest.raises(SigningError, match="RSA or P-256"):
        sign(key_pem, issuer="c", subject="c", audience="aud", cert_pem=cert_pem)
    with pytest.raises(SigningError, match="not a private key"):
        # A generated key cut short: PEM-shaped, never a literal key in the repository.
        sign(pair()[0][:80], issuer="c", subject="c", audience="a")


def test_a_certificate_reads_as_its_thumbprint_subject_and_expiry() -> None:
    _, cert_pem, cert = pair(days=20)
    info = read_certificate(cert_pem)
    assert info.thumbprint == hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    assert info.subject == "CN=ops-ai-acme" and info.not_after == NOW + timedelta(days=20)
    assert info.expires_soon(NOW) and not info.expired(NOW) and info.expired(NOW + timedelta(days=21))
    assert not read_certificate(pair(days=90)[1]).expires_soon(NOW)
    with pytest.raises(SigningError, match="not a PEM certificate"):
        read_certificate("hello")


def test_a_key_matches_only_its_own_certificate() -> None:
    key_pem, cert_pem, _ = pair()
    other_key, other_cert, _ = pair()
    assert key_matches(key_pem, cert_pem) and key_matches(other_key, other_cert)
    assert not key_matches(key_pem, other_cert) and not key_matches(other_key, cert_pem)
