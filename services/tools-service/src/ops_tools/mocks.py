"""Mock answers (c-332): which one a test call gets, and the answer it gives, in the one executor.

A call gets a mock only when it says `environment: test`. A call that names no environment uses the test credential
(c-330) but never a mock, so a caller that does not say cannot act on fake data; production never reads one. The first
mock in order whose `match` values all equal the call's input answers; else the default; else the call goes to the
system. A delay waits before the answer and a timeout waits the operation's time limit and fails as a real timeout does
(`UPSTREAM_TIMEOUT`, the system's side), both capped, so a mock cannot hold a worker longer than a real call could.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast

from .auth.kinds import TEST
from .store.mocks import MockStore

# The longest a mock waits, whatever its delay or the operation's limit says.
MAX_WAIT_MS = 30_000

Sleep = Callable[[float], Awaitable[None]]


def chosen(mocks: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any] | None:
    for m in mocks:
        match = cast(dict[str, Any], m.get("match") or {})
        if match and all(args.get(k) == v for k, v in match.items()):
            return m
    return next((m for m in mocks if m["is_default"]), None)


class MockAnswers:
    def __init__(self, store: MockStore, sleep: Sleep = asyncio.sleep) -> None:
        self.store = store
        self.sleep = sleep

    async def for_call(
        self, tenant_id: str, operation: str, args: dict[str, Any], environment: str | None
    ) -> dict[str, Any] | None:
        if environment != TEST:
            return None
        return chosen(await self.store.listed(tenant_id, operation, TEST), args)

    async def wait(self, mock: dict[str, Any], limit_ms: int) -> None:
        """A timeout waits the operation's limit; a delay its own time, never past the limit; both capped."""
        wait_ms = limit_ms if mock["timeout"] else min(int(mock["delay_ms"] or 0), limit_ms)
        if wait_ms:
            await self.sleep(min(wait_ms, MAX_WAIT_MS) / 1000)
