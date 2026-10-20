"""Secrets at rest, one way for every service (c-189): the cipher port and its AES-256-GCM implementation, a 12-byte
random nonce and a 16-byte tag, stored as base64 of nonce, ciphertext and tag. The tenant and the secret's name are
authenticated as associated data, so a stored value moved to another name or tenant fails to decrypt instead of being
used there. tools-service seals tool secrets with it and files-service storage credentials (as JSON); a key management
service replaces `AesGcmCipher` behind the same port."""

from __future__ import annotations

import base64
import os
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12


class CipherError(ValueError):
    """A stored value that does not decrypt under this key for this tenant and name."""


class Cipher(Protocol):
    def encrypt(self, plaintext: str, *, context: str) -> str: ...

    def decrypt(self, blob: str, *, context: str) -> str: ...


class AesGcmCipher:
    def __init__(self, key_hex: str) -> None:
        key = bytes.fromhex(key_hex)
        if len(key) != 32:
            raise ValueError("The secrets key must be 32 bytes (64 hex characters).")
        self._aead = AESGCM(key)

    def encrypt(self, plaintext: str, *, context: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, plaintext.encode(), context.encode())
        return base64.b64encode(nonce + sealed).decode()

    def decrypt(self, blob: str, *, context: str) -> str:
        try:
            raw = base64.b64decode(blob, validate=True)
            return self._aead.decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], context.encode()).decode()
        except (InvalidTag, ValueError) as e:
            raise CipherError("The stored value does not decrypt for this secret.") from e


def context_of(tenant_id: str, name: str) -> str:
    return f"{tenant_id}/{name}"
