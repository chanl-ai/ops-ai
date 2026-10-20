# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Storage credentials at rest: AES-256-GCM under the service's `secrets_key`, a 12-byte random nonce and a 16-byte
tag, stored as base64 of nonce, ciphertext and tag. The tenant and the credential's name are authenticated as
associated data, so a stored value moved to another name or tenant fails to decrypt instead of being used there.

The cipher is the one every service seals with (`ops_policy.cipher`); the keys stay in the process that hosts files
(enterprise-deployment, "Separation"), so the two services share code, not credentials."""

from __future__ import annotations

import json
from typing import Literal

from ops_policy import AesGcmCipher, CipherError

CredentialKind = Literal["aws_access_key", "azure_service_principal"]

# The fields each kind needs; a credential is stored only when every one is present.
FIELDS: dict[CredentialKind, tuple[str, ...]] = {
    "aws_access_key": ("accessKeyId", "secretAccessKey"),
    "azure_service_principal": ("tenantId", "clientId", "clientSecret"),
}

__all__ = ["FIELDS", "CipherError", "CredentialCipher", "CredentialKind"]


class CredentialCipher:
    """A storage credential's fields as JSON, sealed with the one secrets cipher (ops_policy, c-189)."""

    def __init__(self, key_hex: str) -> None:
        self._cipher = AesGcmCipher(key_hex)

    def seal(self, tenant: str, name: str, fields: dict[str, str]) -> str:
        return self._cipher.encrypt(json.dumps(fields), context=f"{tenant}/{name}")

    def open(self, tenant: str, name: str, blob: str) -> dict[str, str]:
        try:
            plain = self._cipher.decrypt(blob, context=f"{tenant}/{name}")
        except CipherError as e:
            raise CipherError(f"storage credential {name} does not decrypt for this tenant") from e
        return dict(json.loads(plain))
