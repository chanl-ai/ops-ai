"""The workspace's memory retention and clean-up (c-206, c-557). Each pass, per tenant: forgotten memories whose 30-day
grace has ended are erased with their earlier versions, suggestions nobody answered in SUGGESTION_LIFETIME are erased,
and memories older than the tenant's `memoryRetentionDays` policy (platform, Govern > Policies) are deleted; each
deletion is audited and each team whose memories changed gets a background job. No policy, or a policy that cannot be
read, keeps every memory in use: a failed read must never delete a person's memories. A conflict waits for the person
however old it is."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.logging import get_logger
from ops_store import background, isolation
from ops_store.background import HeartbeatStore

from ..store.background import BackgroundJobs
from ..store.memories import Memories
from ..store.tenancy import MEMORY_RETENTION
from .deps import Runtime
from .runs import graph_store

log = get_logger("ops_agents.memory_retention")

POLICY = "memoryRetentionDays"
ACTOR = "retention policy"
# Retention is counted in days, so checking once an hour deletes a memory at most an hour late.
INTERVAL_SECONDS = 3600.0
PROCESS = "memory_cleanup"
# A suggestion the person has not answered in this long is erased: they did not want it kept.
SUGGESTION_LIFETIME = timedelta(days=14)


class RetentionPolicy(Protocol):
    async def days(self) -> float | None:
        """The current tenant's retention in days; None keeps memories."""
        ...


class PlatformRetention:
    """Reads the policy from platform-service through ServiceClient for the current tenant; with no client (no service
    signing key) memories are kept."""

    def __init__(self, platform: ServiceClient | None) -> None:
        self.platform = platform

    async def days(self) -> float | None:
        if self.platform is None:
            return None
        try:
            value: Any = cast(dict[str, Any], await self.platform.get(f"/v1/policies/{POLICY}") or {}).get("value")
        except (ServiceCallError, ServiceUnreachable) as e:
            log.warning("retention policy unread; keeping memories", extra={"error": str(e)})
            return None
        # A boolean is a switch policy, not a number of days (bool is an int in Python).
        return float(value) if isinstance(value, int | float) and not isinstance(value, bool) and value > 0 else None


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def expire_memories(rt: Runtime, policy: RetentionPolicy, now: datetime | None = None) -> int:
    """One pass over every tenant holding memories; the number erased or deleted."""
    store = Memories(graph_store(rt).engine)
    jobs = BackgroundJobs(graph_store(rt).engine)
    at = now or datetime.now(UTC)

    async def one(tenant: str) -> int:
        # Its own task, so the tenant set here never leaks into the loop's context or another tenant's pass.
        with isolation.tenant_wide(MEMORY_RETENTION, tenant_id=tenant):
            erased = await store.erase_due(_iso(at), actor=ACTOR)
            unanswered = await store.expire_suggestions(_iso(at - SUGGESTION_LIFETIME), actor=ACTOR)
            days = await policy.days()
            expired: Counter[str] = Counter()
            if days is not None:
                expired = await store.expire(_iso(at - timedelta(days=days)), actor=ACTOR)
            # A job belongs to a team, so each team whose memories changed gets one.
            for team in sorted({*erased, *unanswered, *expired}):
                summary = f"{erased[team]} erased, {unanswered[team]} unanswered suggestions erased, "
                await jobs.record(PROCESS, summary + f"{expired[team]} past retention deleted", "done", team_id=team)
            return sum((erased + unanswered + expired).values())

    deleted = 0
    for tenant in await store.tenants():
        try:
            deleted += await asyncio.create_task(one(tenant))
        except Exception as e:  # One tenant's failure must not stop the others.
            log.exception("memory_retention_failed", tenant=tenant, error=type(e).__name__)
    return deleted


async def expire_forever(
    rt: Runtime, policy: RetentionPolicy, *, beats: HeartbeatStore, interval: float = INTERVAL_SECONDS
) -> None:
    """Memory clean-up, a listed background process: a failed pass is retried and shows in its heartbeat. The first
    pass waits one interval, as before, so a restart loop never runs it again and again."""

    async def once() -> int:
        return await expire_memories(rt, policy)

    await background.run(PROCESS, once, stop=asyncio.Event(), store=beats, every_s=interval, first_in=interval)
