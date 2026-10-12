"""The scheduler port for timers (ADR-0016). The `timers` table is the source of truth and `fire` the only way a timer
fires; a scheduler only has to wake the fire endpoint at, or after, a timer's due time.

`schedule` and `cancel` tell a scheduler that keeps its own queue (pg_cron, a cloud scheduler, a Temporal timer)
what to wake and what to forget. The PostgreSQL poller reads the table directly, so its adapter does nothing. A
missed `cancel` costs a refused fire, a missed `schedule` costs the timer until the poller sees it, which is why the
poller stays on under any other scheduler.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class TimerScheduler(Protocol):
    async def schedule(self, thread_id: str, timer_id: str, due_at: datetime) -> None: ...
    async def cancel(self, thread_id: str, timer_id: str) -> None: ...


class PollingScheduler:
    """The only scheduler shipped: the poller finds due timers in the table, so there is nothing to tell it."""

    async def schedule(self, thread_id: str, timer_id: str, due_at: datetime) -> None:
        return None

    async def cancel(self, thread_id: str, timer_id: str) -> None:
        return None
