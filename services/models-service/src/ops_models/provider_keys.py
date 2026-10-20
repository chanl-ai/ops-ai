"""A provider connection's key, by the name it gives (`key_ref`), read from the Secrets store (c-177, c-221): tools-
service's service route, as this service for the deployment's tenant, each read audited there. A key is kept for a
minute so a call does not wait on tools-service, and a rotation applies within that minute.

Dev-only exception (owner, 2026-10-18): until Govern > Models takes provider keys, the shared dev stack's key may come
from settings (`OPS_MODEL_PROVIDER_KEYS`, filled from .env by scripts/stack.sh); a key saved in Secrets wins over it.
Outside dev a key in settings stops start-up (see __main__)."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.logging import get_logger

log = get_logger("ops_models.provider_keys")


class ProviderKeys:
    def __init__(
        self,
        secrets: ServiceClient | None,
        fallback: Mapping[str, str] | None = None,
        *,
        ttl_s: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`secrets` calls tools-service as models-service holding `secrets_egress:run`, for the tenant whose secrets
        hold the provider keys; `fallback` is the dev stack's keys from settings."""
        self.secrets = secrets
        self.fallback = dict(fallback or {})
        self.ttl_s = ttl_s
        self.clock = clock
        self._cache: dict[str, tuple[float, str | None]] = {}

    async def get(self, name: str) -> str | None:
        """The key saved as `name`, or None when neither Secrets nor the dev settings hold it."""
        hit = self._cache.get(name)
        if hit is not None and self.clock() - hit[0] < self.ttl_s:
            return hit[1]
        value = await self._read(name)
        if value is None:
            value = self.fallback.get(name)
        self._cache[name] = (self.clock(), value)
        return value

    async def _read(self, name: str) -> str | None:
        if self.secrets is None:
            return None
        try:
            data = await self.secrets.post("/v1/secrets/values", json={"names": [name]})
        except ServiceCallError as e:
            # 404: not saved yet; anything else (a team-scoped secret, a scope refused) is logged, never the value.
            if e.status != 404:
                log.warning("provider_key_unreadable", name=name, status=e.status, code=e.code)
            return None
        except ServiceUnreachable:
            log.warning("provider_key_unreadable", name=name, status=None, code="unreachable")
            return None
        answer = cast(dict[str, Any], data) if isinstance(data, dict) else {}
        values = cast(dict[str, Any], answer.get("values") or {})
        value = values.get(name)
        return str(value) if value else None
