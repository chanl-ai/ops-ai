"""The knowledge schedule: a beat that syncs each source when its schedule says, in the source's team, and asks again
for the reading of every file source item still waiting on one, so an item is indexed even when documents-service's
reading.finished event never arrived.

Every minute it reads each tenant's sources, of every kind, and syncs each one that is due by the one schedule rule
(ops_store.schedule): manual never, every N hours, daily at a time, or weekly on a day, in the schedule's time zone.
The sync takes the source's lease, so a manual sync, a rebuild and the beat, or two kb-service processes, never run
one source at once. A source paused, waiting for a reconnect, or whose plugin is off answers as its sync would and is
tried again at the next due time."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from ops_service_kit.errors import ApiError
from ops_service_kit.logging import get_logger
from ops_store import background, isolation
from ops_store.schedule import due as schedule_due

from .service import KnowledgeService, Who

log = get_logger(__name__)

FIND_DUE = "background process: the knowledge schedule reads each tenant's tool sources to find the due ones"
FIND_READING = "background process: the knowledge schedule reads each tenant's items waiting for their file's reading"
FIND_STALE = "background process: the knowledge schedule ends each tenant's runs left running by a stopped process"
# A run still marked running this long after it started belongs to a process that stopped: the lease it held ran out.
STALE_AFTER = timedelta(minutes=15)


def due(service: KnowledgeService, s: dict[str, Any], now: datetime) -> bool:
    """A source not paused whose schedule (ops_store.schedule, the one rule) asks for a run since its last sync."""
    if s["status"] == "paused":
        return False
    return schedule_due(service.schedule_of(s), s.get("last_sync_at"), now)


async def run_due(service: KnowledgeService, now: datetime) -> list[str]:
    """Syncs every source that is due, of every kind, each in its own team and under its lease; returns the ids it
    synced. A tool source is read only where this service reads tools."""
    ran: list[str] = []
    for tenant in await service.store.tenants():
        with isolation.tenant_wide(FIND_DUE, tenant_id=tenant):
            readable = [s for s in await service.store.sources(tenant) if s["type"] != "tool" or service.tools]
            sources = [s for s in readable if due(service, s, now)]
        for s in sources:
            with isolation.scope(tenant, str(s["team_id"])):
                who = Who(tenant, "knowledge schedule", str(s["team_id"]))
                try:
                    await service.scheduled_sync(who, s)
                    ran.append(str(s["id"]))
                except ApiError as e:
                    log.info("kb_schedule_skipped", source=s["id"], code=e.code)
    return ran


async def finish_readings(service: KnowledgeService) -> int:
    """Asks documents-service again for each file items still wait on; the number of items settled."""
    if service.readings is None:
        return 0
    settled = 0
    for tenant in await service.store.tenants():
        with isolation.tenant_wide(FIND_READING, tenant_id=tenant):
            waiting = {(str(i["team_id"]), str(i["file_id"])) for i in await service.store.reading_items(tenant)}
        for team, file_id in sorted(waiting):
            with isolation.scope(tenant, team):
                settled += await service.finish_reading(Who(tenant, "knowledge schedule", team), file_id)
    return settled


async def end_stale_runs(service: KnowledgeService, now: datetime) -> int:
    """Ends rebuilds and syncs a stopped process left marked running, saying why; the number ended."""
    ended = 0
    for tenant in await service.store.tenants():
        with isolation.tenant_wide(FIND_STALE, tenant_id=tenant):
            ended += await service.store.end_stale_runs(
                tenant, before=now - STALE_AFTER, reason="Stopped when the service stopped; sync again to finish."
            )
    return ended


async def keep_syncing(service: KnowledgeService, stop: asyncio.Event) -> None:
    """The listed `knowledge_schedule` process: one pass a minute through the shared runner, which reports it on
    /health/background and backs off after a failed pass."""

    async def once() -> int:
        now = datetime.now(UTC)
        synced = len(await run_due(service, now))
        return synced + await finish_readings(service) + await end_stale_runs(service, now)

    await background.run("knowledge_schedule", once, stop=stop, store=background.LOCAL)
