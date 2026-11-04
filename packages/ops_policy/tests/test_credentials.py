"""The credential store port, by failure mode: rows written before the port stop opening (the reference the
row-sealed adapter hands back must be the cipher's own format, so no row moves), and a reference copied to another
tenant or name opening there."""

from __future__ import annotations

import asyncio

import pytest

from ops_policy import AesGcmCipher, CipherError, CredentialStore, InMemoryVault, RowSealed, context_of

KEY = "ab" * 32


def test_a_row_sealed_before_the_port_opens_through_it() -> None:
    before = AesGcmCipher(KEY).encrypt("s3cret", context=context_of("ten_a", "BANK_API"))
    store: CredentialStore = RowSealed(AesGcmCipher(KEY))
    assert asyncio.run(store.get(before, context=context_of("ten_a", "BANK_API"))) == "s3cret"


def test_a_reference_copied_to_another_tenant_or_name_does_not_open() -> None:
    store: CredentialStore = RowSealed(AesGcmCipher(KEY))
    ref = asyncio.run(store.put("s3cret", context=context_of("ten_a", "BANK_API")))
    assert "s3cret" not in ref
    for other in (context_of("ten_b", "BANK_API"), context_of("ten_a", "OTHER")):
        with pytest.raises(CipherError):
            asyncio.run(store.get(ref, context=other))


def test_a_vault_adapter_refuses_a_reference_read_under_another_context_or_after_delete() -> None:
    first, second = InMemoryVault(), InMemoryVault()
    ref = asyncio.run(first.put("s3cret", context=context_of("ten_a", "BANK_API")))
    assert "s3cret" not in ref
    assert asyncio.run(second.get(ref, context=context_of("ten_a", "BANK_API"))) == "s3cret", "one vault per process"
    with pytest.raises(CipherError):
        asyncio.run(second.get(ref, context=context_of("ten_b", "BANK_API")))
    asyncio.run(first.delete(ref, context=context_of("ten_a", "BANK_API")))
    with pytest.raises(CipherError):
        asyncio.run(second.get(ref, context=context_of("ten_a", "BANK_API")))
