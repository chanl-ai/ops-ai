"""A module's traffic comes from gateway_calls (c-041): the window, what counts as a call, and the module's own p95."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import new_id
from ops_tools.store.calls import CallLog

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def logged(log: CallLog, module_id: str, tool: str, *, outcome: str, latency: int, at: datetime) -> None:
    row: dict[str, Any] = {
        "id": new_id("call"),
        "tool": tool,
        "access": "read",
        "input_hash": new_id("h"),
        "idempotency_key": new_id("k"),
        "sub": "agent:test",
        "decision": "deny" if outcome == "refused" else "allow",
        "reasons": [],
        "approvers": [],
        "outcome": outcome,
        "created_at": iso(at),
        "module_id": module_id,
        "latency_ms": latency,
    }
    await log.record(**row)


async def test_traffic_counts_calls_that_ran_in_the_window(engine: AsyncEngine) -> None:
    log = CallLog(engine)
    mod, other = new_id("mod"), new_id("mod")
    for ms in (10, 20, 30, 40):
        await logged(log, mod, "fast", outcome="ok", latency=ms, at=NOW - timedelta(hours=1))
    await logged(log, mod, "slow", outcome="error", latency=900, at=NOW - timedelta(hours=2))
    await logged(log, mod, "fast", outcome="refused", latency=1, at=NOW - timedelta(hours=1))
    await logged(log, mod, "fast", outcome="replayed", latency=1, at=NOW - timedelta(hours=1))
    await logged(log, mod, "fast", outcome="ok", latency=5000, at=NOW - timedelta(hours=25))
    await logged(log, other, "fast", outcome="ok", latency=10, at=NOW - timedelta(hours=1))

    t = await log.traffic([mod], iso(NOW - timedelta(days=1)))

    assert t[(mod, "fast")] == {"calls": 4, "errors": 0, "p95Ms": 38}
    assert t[(mod, "slow")] == {"calls": 1, "errors": 1, "p95Ms": 900}
    # The module's p95 is over all five calls, not the larger of its operations' p95s.
    assert t[(mod, None)]["calls"] == 5 and t[(mod, None)]["errors"] == 1
    assert 38 < t[(mod, None)]["p95Ms"] < 900
    assert all(k[0] == mod for k in t)


async def test_daily_groups_by_utc_day(engine: AsyncEngine) -> None:
    log = CallLog(engine)
    mod = new_id("mod")
    await logged(log, mod, "op", outcome="ok", latency=10, at=NOW)
    await logged(log, mod, "op", outcome="error", latency=10, at=NOW - timedelta(hours=1))
    await logged(log, mod, "op", outcome="ok", latency=10, at=NOW - timedelta(days=3))
    await logged(log, mod, "op", outcome="ok", latency=10, at=NOW - timedelta(days=20))

    days = await log.daily(mod, (NOW - timedelta(days=13)).date().isoformat())

    assert days == {
        "2026-10-12": {"count": 2, "errors": 1, "p95Ms": 10},
        "2026-10-09": {"count": 1, "errors": 0, "p95Ms": 10},
    }
