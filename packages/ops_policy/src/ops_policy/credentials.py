"""The credential store port (c-616 C6): every secret value a service keeps, a tool secret, an app credential's secret,
a sign-in's token or verifier, a person's own key or a model provider key, is put and read through it, and the row that
uses the value keeps only the reference `put` returns, beside its plain metadata (name, version, who set it, when).

What a reference is belongs to the adapter. With `RowSealed`, today's adapter, the reference is the value sealed by the
cipher (AES-256-GCM, the context as associated data), so the row holds the sealed value itself and rows written before
the port open unchanged. A vault adapter (a bank's own Azure Key Vault or HashiCorp Vault) keeps the value in the vault
and hands back the vault's secret id; adding one changes no row shape, store or caller.

`context` names whose value it is and which one (`context_of(tenant, name)` and the like). The row-sealed adapter
authenticates it, so a reference copied to another tenant or name does not open there; a vault adapter names the secret
by it and refuses a reference read under another. Every method is async because a vault is a network call."""

from __future__ import annotations

import uuid
from typing import Protocol

from .cipher import Cipher, CipherError


class CredentialUnreadable(CipherError):
    """A reference that does not open under this context: moved to another tenant or name, sealed under another key, or
    gone from the vault. A CipherError, so every caller that refuses a value that no longer opens refuses this too."""


class CredentialStore(Protocol):
    async def put(self, value: str, *, context: str) -> str:
        """Keeps `value` for `context` and returns the reference the row stores."""
        ...

    async def get(self, ref: str, *, context: str) -> str:
        """The value behind `ref`; CipherError when it does not open for `context`."""
        ...

    async def delete(self, ref: str, *, context: str) -> None:
        """Forgets the value behind `ref` once its row no longer names it (a delete, or a rotation's old reference)."""
        ...


class RowSealed:
    """The value sealed into the reference itself, which the row keeps: nothing is held outside the database, and
    deleting the row deletes the value, so `delete` has nothing left to do."""

    def __init__(self, cipher: Cipher) -> None:
        self._cipher = cipher

    async def put(self, value: str, *, context: str) -> str:
        return self._cipher.encrypt(value, context=context)

    async def get(self, ref: str, *, context: str) -> str:
        return self._cipher.decrypt(ref, context=context)

    async def delete(self, ref: str, *, context: str) -> None:
        return None


# The memory vault's values, shared by every adapter in the process as a vault's are by every client of it.
_VAULT: dict[str, tuple[str, str]] = {}


class InMemoryVault:
    """A vault held in this process's memory, for tests: values live outside the rows, which keep only a `vault:` id,
    as with a real vault adapter. Every value is lost when the process ends, so Settings refuses it outside dev and
    test."""

    async def put(self, value: str, *, context: str) -> str:
        ref = f"vault:{uuid.uuid4().hex}"
        _VAULT[ref] = (context, value)
        return ref

    async def get(self, ref: str, *, context: str) -> str:
        held = _VAULT.get(ref)
        if held is None or held[0] != context:
            raise CredentialUnreadable("The vault holds no value for this secret under that reference.")
        return held[1]

    async def delete(self, ref: str, *, context: str) -> None:
        held = _VAULT.get(ref)
        if held is not None and held[0] == context:
            del _VAULT[ref]

    def holds(self, ref: str) -> bool:
        """Whether the vault still keeps a value under `ref`: what a test reads to prove nothing was left behind."""
        return ref in _VAULT
