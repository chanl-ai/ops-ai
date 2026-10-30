"""The knowledge schedule (c-564): a beat that syncs each tool source when its schedule says, in the source's team.

Every minute it reads each tenant's tool sources, and syncs each one that is due: never synced, or a daily source
whose time of day has passed since its last sync, or a weekly one a week on. The sync takes the source's lease
(`KnowledgeService.sync_tool`), so a manual sync and the beat, or two kb-service processes, never run one source at
once. A source paused, waiting for a reconnect, or whose plugin is off answers as its sync would and is tried again
at the next beat."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, time, timedelta
from typing import Any, cast

from ops_service_kit.errors import ApiError
from ops_service_kit.logging import get_logger
from ops_store import background, isolation

from .service import KnowledgeService, Who

log = get_logger(__name__)

FIND_DUE = "background process: the knowledge schedule reads each tenant's tool sources to find the due ones"


def due(s: dict[str, Any], now: datetime) -> bool:
    cfg = cast(dict[str, Any], s.get("config") or {})
    schedule = cast(dict[str, Any], cfg.get("schedule") or {})
    kind = schedule.get("kind", "manual")
    last: datetime | None = s.get("last_sync_at")
    if kind == "manual" or s["status"] == "paused":
        return False
    if last is None:
        return True
    hour, _, minute = str(schedule.get("time") or "00:00").partition(":")
    at = datetime.combine(now.date(), time(int(hour or 0), int(minute or 0)), tzinfo=UTC)
    if at > now:
        at -= timedelta(days=1)
    if kind == "weekly":
        return now - last >= timedelta(days=7) and last < at
    return last < at


async def run_due(service: KnowledgeService, now: datetime) -> list[str]:
    """Syncs every tool source that is due; returns the ids it synced."""
    ran: list[str] = []
    for tenant in await service.store.tenants():
        with isolation.tenant_wide(FIND_DUE, tenant_id=tenant):
            sources = [s for s in await service.store.sources(tenant) if s["type"] == "tool" and due(s, now)]
        for s in sources:
            with isolation.scope(tenant, str(s["team_id"])):
                try:
                    await service.sync_tool(
                        Who(tenant, "knowledge schedule", str(s["team_id"])), s, full=False, trigger="schedule"
                    )
                    ran.append(str(s["id"]))
                except ApiError as e:
                    log.info("kb_schedule_skipped", source=s["id"], code=e.code)
    return ran


async def keep_syncing(service: KnowledgeService, stop: asyncio.Event) -> None:
    """The listed `knowledge_schedule` process: one pass a minute through the shared runner, which reports it on
    /health/background and backs off after a failed pass."""

    async def once() -> int:
        return len(await run_due(service, datetime.now(UTC)))

    await background.run("knowledge_schedule", once, stop=stop, store=background.LOCAL)
