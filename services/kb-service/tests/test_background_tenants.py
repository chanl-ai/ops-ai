"""kb's background jobs across tenants, on both databases, by failure mode: the listing every loop starts from (the
schedule, the embedding backlog and the start-up move between file stores) reading no tenant, so nothing is synced or
embedded; and the relay reading or marking no tenant's events, so no other service hears of a change. Each would
pass on PostgreSQL, whose system role bypasses row security, and fail on SQL Server if its predicates did not admit
kb's system user."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.agents import StaticAgents
from ops_kb.files import KnowledgeFiles
from ops_kb.schedule import run_due
from ops_kb.search import HybridRetriever
from ops_kb.service import KnowledgeService
from ops_kb.store import KnowledgeStore
from ops_kb.store.knowledge import outbox_relay

from .conftest import kb_client
from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_schedule_health import Agents
from .test_sync import file_source


async def hourly_source_and_base(client: httpx.AsyncClient) -> tuple[str, str]:
    src = await file_source(client)
    data(await client.patch(f"/v1/sources/{src['id']}", json={"schedule": {"kind": "hourly", "every": 1}}))
    base = data(
        await client.post("/v1/knowledge-bases", json={"name": "Claims", "owner": "maya@harborpine.example"}), 201
    )
    return str(src["id"]), str(base["id"])


async def test_each_background_job_reaches_every_tenant(engine: AsyncEngine, tmp_path: Path) -> None:
    tenants = [f"t_{uuid4().hex[:10]}" for _ in range(2)]
    made: dict[str, tuple[str, str]] = {}
    for t in tenants:
        async with kb_client(engine, t) as client:
            made[t] = await hourly_source_and_base(client)
    store = KnowledgeStore(engine)
    assert set(tenants) <= set(await store.tenants())

    intake = KnowledgeFiles(tmp_path)
    service = KnowledgeService(store, intake, HybridRetriever(engine), StaticAgents(), readings=LocalReadings(intake))
    ran = await run_due(service, datetime.now(UTC))
    assert {made[t][0] for t in tenants} <= set(ran), ran

    agents = Agents()
    hand_off = outbox_relay(engine, {"agents": agents.client()})
    # The outbox is every test's, oldest first in batches: deliver until it is empty.
    while await hand_off.once():
        pass
    told = {e["payload"].get("id") for e in agents.events if e["name"] == "kb.changed"}
    assert {made[t][1] for t in tenants} <= told, agents.events
    assert not await hand_off.once()
