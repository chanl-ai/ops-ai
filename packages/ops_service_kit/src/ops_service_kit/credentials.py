"""The credential store a service puts and reads its secret values through (`ops_policy.credentials`), chosen here
from the settings so that switching where values live (a vault adapter) changes this function and nothing else."""

from __future__ import annotations

from ops_policy import AesGcmCipher, CredentialStore, InMemoryVault, RowSealed

from .settings import Settings


def credential_store(settings: Settings) -> CredentialStore:
    """`sealed`: each row keeps its value sealed under the settings' secrets key. `memory`: the process's vault."""
    if settings.credential_store == "memory":
        return InMemoryVault()
    return RowSealed(AesGcmCipher(settings.secrets_key.get_secret_value()))
