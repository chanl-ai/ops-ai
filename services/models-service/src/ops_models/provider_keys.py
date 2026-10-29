"""A provider connection's key, by the name it gives (`key_ref`), from the account's provider keys (owner, 2026-10-27):
models-service's own sealed table, set by account admins on Settings > Model providers. The key of the tenant a call is
for is used, or the deployment's tenant (`model_keys_tenant`) for a call that names none. A key is kept for a minute so
a call does not wait on the database, and an admin's save or delete drops it at once.

Dev-only exception (owner, 2026-10-18): the shared dev stack's key may come from settings (`OPS_MODEL_PROVIDER_KEYS`,
filled from .env by scripts/stack.sh); a key an admin saved wins over it. Outside dev a key in settings stops start-up
(see __main__)."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

from ops_policy import CipherError
from ops_service_kit.logging import get_logger

from .store import ProviderKeyStore

log = get_logger("ops_models.provider_keys")


class ProviderKeys:
    def __init__(
        self,
        store: ProviderKeyStore | None,
        fallback: Mapping[str, str] | None = None,
        *,
        tenant: str = "local",
        ttl_s: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`store` holds the accounts' keys; `fallback` is the dev stack's keys from settings; `tenant` is the
        deployment's, for a call that names no tenant."""
        self.store = store
        self.fallback = dict(fallback or {})
        self.tenant = tenant
        self.ttl_s = ttl_s
        self.clock = clock
        self._cache: dict[tuple[str, str], tuple[float, str | None]] = {}

    async def get(self, name: str, tenant_id: str | None = None) -> str | None:
        """The key saved as `name` for the call's tenant, or None when neither the account nor the dev settings hold
        it."""
        at = (tenant_id or self.tenant, name)
        hit = self._cache.get(at)
        if hit is not None and self.clock() - hit[0] < self.ttl_s:
            return hit[1]
        value = await self._read(*at)
        if value is None:
            value = self.fallback.get(name)
        self._cache[at] = (self.clock(), value)
        return value

    def forget(self, tenant_id: str, name: str) -> None:
        """Drops a cached key, so the next call reads what an admin just saved or deleted."""
        self._cache.pop((tenant_id, name), None)

    async def _read(self, tenant_id: str, name: str) -> str | None:
        if self.store is None:
            return None
        try:
            return await self.store.value(tenant_id, name)
        except CipherError:
            # The secrets key changed since the value was sealed: the admin saves the key again. Never the value.
            log.warning("provider_key_unreadable", name=name, tenant_id=tenant_id)
            return None
