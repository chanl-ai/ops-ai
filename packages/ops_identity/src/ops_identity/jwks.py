"""platform-service's public keys, cached by `kid`.

A token naming a `kid` the cache does not hold triggers one refetch, so a key rotation is picked up on first use.
Refetches are spaced by `refetch_s` and a `kid` still unknown after one is remembered, so a stream of tokens with
invented kids cannot turn every request into a call to platform-service.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from ops_policy import Ed25519Verifier, TokenError

JwksFetch = Callable[[], Awaitable[dict[str, Any]]]


class JwksCache:
    def __init__(
        self, fetch: JwksFetch, audience: str, *, refetch_s: float = 30.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.fetch = fetch
        self.audience = audience
        self.refetch_s = refetch_s
        self.clock = clock
        self.keys: dict[str, Ed25519Verifier] | None = None
        self.last_refetch: float | None = None
        self.unknown: set[str] = set()

    async def _load(self) -> None:
        document = await self.fetch()
        keys: dict[str, Ed25519Verifier] = {}
        for jwk in document.get("keys", []):
            try:
                verifier = Ed25519Verifier.from_jwk(jwk, self.audience)
            except TokenError:
                continue
            keys[verifier.kid] = verifier
        self.keys = keys
        self.unknown -= set(keys)

    async def verifier(self, kid: str) -> Ed25519Verifier | None:
        if self.keys is None:
            await self._load()
        assert self.keys is not None
        if kid in self.keys:
            return self.keys[kid]
        now = self.clock()
        recent = self.last_refetch is not None and now - self.last_refetch < self.refetch_s
        if kid in self.unknown or recent:
            return None
        self.last_refetch = now
        await self._load()
        found = self.keys.get(kid)
        if found is None:
            self.unknown.add(kid)
        return found
