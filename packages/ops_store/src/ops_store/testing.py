"""Test helpers for a service's own suite. `loop_reports_failure` is the one test every background process has
(tests/test_loop_health.py): that a pass which raises shows on the service's `/health/background`.

  async def test_the_relay_reports_a_failed_pass(client, agents):
      await loop_reports_failure(client, "files_relay", lambda: agents.go_down())
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from typing import Any, Protocol, cast

from . import background

# How often the report is read while waiting for the failure to show.
POLL_S = 0.05
# The longest wait for a process whose listed interval is longer; its test runs the loop on a short interval.
WAIT_MAX_S = 10.0


class Reply(Protocol):
    def json(self) -> Any: ...


class HealthClient(Protocol):
    """The part of an HTTP test client the check uses; `httpx.AsyncClient` on the service's app is one."""

    async def get(self, url: str, /) -> Reply: ...


async def _row(client: HealthClient, key: str) -> dict[str, Any]:
    answer: Any = (await client.get("/health/background")).json()
    body = cast(dict[str, Any], answer)
    # A service answers the bare report; one behind the response envelope carries it under `data`.
    listed = cast(list[dict[str, Any]], (body.get("data") or body).get("processes") or [])
    row = next((p for p in listed if p.get("key") == key), None)
    assert row is not None, f"/health/background does not list {key}; it shows {[p.get('key') for p in listed]}"
    return row


async def loop_reports_failure(
    client: HealthClient, key: str, trip: Callable[[], None], *, within_s: float | None = None
) -> None:
    """Makes one pass raise, waits one interval, asserts /health/background shows the key with last_error set.

    `trip` arranges for the process's next pass to raise (a dependency taken down, a store method that throws). The
    loop must already be running on the app `client` calls. The wait is the process's listed interval plus its first
    retry, at most WAIT_MAX_S, or `within_s`. The error has to be newer than any the report showed before `trip`,
    so an old failure, or a loop that never reaches its heartbeat, fails. The state is not asserted: a pass that
    fails once has recovered, and reads as running again, by the time the report is read."""
    process = background.BY_KEY.get(key)
    assert process is not None, f"{key} is not on ops_store.background.PROCESSES"
    before = (await _row(client, key)).get("lastErrorAt") or 0.0
    trip()
    wait = within_s if within_s is not None else min(WAIT_MAX_S, (process.every_s or 0.0) + background.BACKOFF_START_S)
    row: dict[str, Any] = {}
    for _ in range(math.ceil(wait / POLL_S) + 1):
        row = await _row(client, key)
        if row.get("lastError") and (row.get("lastErrorAt") or 0.0) > before:
            return
        await asyncio.sleep(POLL_S)
    raise AssertionError(
        f"{key} did not report a failed pass on /health/background within {wait:g} s of the trip; its row: {row}"
    )
