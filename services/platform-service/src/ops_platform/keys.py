"""The private key platform-service signs tokens with, and nothing else holds.

Outside dev the key comes from the environment (your secrets manager). In dev it is derived from a fixed, public seed,
so tokens survive a restart and every local service resolves the same `kid`; such a token proves nothing outside dev.
"""

from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ops_policy import Ed25519Signer
from ops_service_kit.settings import Settings

DEV_KID = "platform-dev"
_DEV_SEED = hashlib.sha256(b"ops-platform dev signing key: public, dev only").digest()


def dev_signer() -> Ed25519Signer:
    return Ed25519Signer(Ed25519PrivateKey.from_private_bytes(_DEV_SEED), DEV_KID)


def signer_from(settings: Settings) -> Ed25519Signer:
    if settings.platform_signing_key is not None:
        return Ed25519Signer.from_private_text(
            settings.platform_signing_key.get_secret_value(), settings.platform_signing_kid
        )
    if settings.environment == "dev":
        return dev_signer()
    raise ValueError("platform_signing_key must be set outside dev; the dev key is derived from a public seed")
