"""The keys services sign each other's tokens with, from Settings.

Each service holds its own private key, and a callee trusts a set of public keys, each bound to the one service
that may use it, so a token's `sub` is proven by the key that signed it. In dev both sides derive the same key from a
public seed under kid `svc-dev`, accepted for any service and only in dev.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ops_policy import Ed25519Signer, Ed25519Verifier
from ops_service_kit.settings import Settings

DEV_KID = "svc-dev"
_DEV_SEED = hashlib.sha256(b"ops service-to-service dev key: public, dev only").digest()

# kid -> (verifier, the service it is bound to, or None for the dev key, which any service may use in dev).
Verifiers = dict[str, tuple[Ed25519Verifier, str | None]]


def dev_service_signer() -> Ed25519Signer:
    return Ed25519Signer(Ed25519PrivateKey.from_private_bytes(_DEV_SEED), DEV_KID)


def service_signer(settings: Settings) -> Ed25519Signer:
    if settings.service_signing_key is not None:
        return Ed25519Signer.from_private_text(
            settings.service_signing_key.get_secret_value(), settings.service_signing_kid
        )
    if settings.environment == "dev":
        return dev_service_signer()
    raise ValueError("service_signing_key must be set outside dev; the dev key is derived from a public seed")


def service_verifiers(settings: Settings, audience: str) -> Verifiers:
    found: Verifiers = {}
    for kid, entry in settings.service_public_keys.items():
        raw = base64.urlsafe_b64decode(entry["x"] + "=" * (-len(entry["x"]) % 4))
        found[kid] = (Ed25519Verifier(Ed25519PublicKey.from_public_bytes(raw), kid, audience), entry["service"])
    if settings.environment == "dev":
        found[DEV_KID] = (dev_service_signer().verifier(audience), None)
    return found
