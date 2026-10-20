"""The one cipher for secrets at rest (c-189), by failure mode: a value that no longer opens after the move from
tools-service and files-service (the format must not change), and a value moved to another tenant or name opening
there."""

from __future__ import annotations

import base64
import json
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ops_policy import AesGcmCipher, CipherError, context_of

KEY = "ab" * 32


def sealed_the_old_way(plaintext: str, context: str) -> str:
    """What tools-service's and files-service's copies wrote: base64 of nonce, ciphertext and tag, context as AAD."""
    nonce = os.urandom(12)
    return base64.b64encode(
        nonce + AESGCM(bytes.fromhex(KEY)).encrypt(nonce, plaintext.encode(), context.encode())
    ).decode()


def test_values_sealed_by_the_old_modules_open() -> None:
    cipher = AesGcmCipher(KEY)
    assert (
        cipher.decrypt(sealed_the_old_way("s3cret", "ten_a/BANK_API"), context=context_of("ten_a", "BANK_API"))
        == "s3cret"
    )
    fields = {"accessKeyId": "a", "secretAccessKey": "b"}
    opened = cipher.decrypt(sealed_the_old_way(json.dumps(fields), "ten_a/bank-s3"), context="ten_a/bank-s3")
    assert json.loads(opened) == fields


def test_a_value_moved_to_another_tenant_or_name_does_not_open() -> None:
    cipher = AesGcmCipher(KEY)
    blob = cipher.encrypt("s3cret", context=context_of("ten_a", "BANK_API"))
    assert cipher.decrypt(blob, context=context_of("ten_a", "BANK_API")) == "s3cret"
    for other in (context_of("ten_b", "BANK_API"), context_of("ten_a", "OTHER")):
        with pytest.raises(CipherError):
            cipher.decrypt(blob, context=other)
