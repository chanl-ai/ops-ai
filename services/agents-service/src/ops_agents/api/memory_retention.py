"""The workspace's memory retention (c-206): memories older than the tenant's `memoryRetentionDays` policy (platform,
Govern > Policies) are deleted and each deletion audited. No policy, or a policy that cannot be read, keeps everything:
a failed read must never delete a person's memories."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.logging import get_logger
from ops_store import background, isolation
from ops_store.background import HeartbeatStore

from ..store.memories import Memories
from ..store.tenancy import MEMORY_RETENTION
from .deps import Runtime
from .runs import graph_store

log = get_logger("ops_agents.memory_retention")

POLICY = "memoryRetentionDays"
ACTOR = "retention policy"
# Retention is counted in days, so checking once an hour deletes a memory at most an hour late.
INTERVAL_SECONDS = 3600.0


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


async def expire_memories(rt: Runtime, policy: RetentionPolicy, now: datetime | None = None) -> int:
    """One pass over every tenant holding memories; the number deleted."""
    store = Memories(graph_store(rt).engine)
    at = now or datetime.now(UTC)

    async def one(tenant: str) -> int:
        # Its own task, so the tenant set here never leaks into the loop's context or another tenant's pass.
        with isolation.tenant_wide(MEMORY_RETENTION, tenant_id=tenant):
            days = await policy.days()
            if days is None:
                return 0
            cutoff = (at - timedelta(days=days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            return await store.expire(cutoff, actor=ACTOR)

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

    await background.run("memory_cleanup", once, stop=asyncio.Event(), store=beats, every_s=interval, first_in=interval)
