"""Knowledge base screens that said more than the service knew, by failure mode: a source counting its pieces as
items, an overview with no index jobs or precedence however often it ran, documents always fresh whatever their
schedule, every non-web source named with the Email templates preset, and Add source offering a source the create then
refuses."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.source_settings import defaults, stored, wire
from ops_kb.store.knowledge import kb_sources
from ops_store import isolation

from .pdfs import HARDSHIP
from .test_bases_and_sources import data
from .test_sync import file_source, upload
from .test_written_sources import BASE


async def base_of(client: httpx.AsyncClient, source_id: str) -> dict[str, Any]:
    return data(await client.post("/v1/knowledge-bases", json={**BASE, "sourceIds": [source_id]}), 201)


async def test_a_source_counts_its_items_not_their_pieces(client: httpx.AsyncClient) -> None:
    src = await file_source(client)
    await upload(client, src["id"], "hardship.pdf", HARDSHIP)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    item = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"][0]
    assert item["chunkCount"] > 1, item  # the fixture has pieces to over-count
    assert data(await client.get(f"/v1/sources/{src['id']}"))["itemCount"] == 1


async def test_refresh_index_records_a_job_the_overview_lists_beside_the_precedence(
    client: httpx.AsyncClient,
) -> None:
    src = await file_source(client)
    await upload(client, src["id"], "hardship.pdf", HARDSHIP)
    kb_row = await base_of(client, src["id"])
    refreshed = data(await client.post(f"/v1/knowledge-bases/{kb_row['id']}/refresh"))
    detail = data(await client.get(f"/v1/knowledge-bases/{kb_row['id']}"))
    for shown in (refreshed, detail):
        [job, *_] = shown["jobs"]
        assert (job["status"], job["processed"], job["trigger"]) == ("success", 1, "manual"), shown["jobs"]
    assert detail["precedence"], "the newer-version rule the index applies is listed"


async def _synced_ago(engine: AsyncEngine, tenant: str, source_id: str, ago: timedelta) -> None:
    at = datetime.now(UTC) - ago
    with isolation.tenant_wide("test: age a source's last sync", tenant_id=tenant):
        async with engine.begin() as c:
            await c.execute(
                sa.update(kb_sources)
                .where(kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
                .values(last_sync_at=at, last_good_sync_at=at)
            )


async def _freshness(client: httpx.AsyncClient, kb_id: str) -> list[str]:
    return [d["freshness"] for d in data(await client.get(f"/v1/knowledge-bases/{kb_id}/documents"))["data"]]


async def test_documents_are_fresh_stale_or_without_a_schedule_from_the_sources_syncs(
    engine: AsyncEngine, tenant: str, client: httpx.AsyncClient
) -> None:
    src = await file_source(client)
    await upload(client, src["id"], "hardship.pdf", HARDSHIP)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    kb_row = await base_of(client, src["id"])
    assert await _freshness(client, kb_row["id"]) == ["no_schedule"]  # a manual source is never "fresh"
    data(await client.patch(f"/v1/sources/{src['id']}", json={"schedule": {"kind": "hourly", "every": 1}}))
    await _synced_ago(engine, tenant, src["id"], timedelta(minutes=5))
    assert await _freshness(client, kb_row["id"]) == ["fresh"]
    await _synced_ago(engine, tenant, src["id"], timedelta(days=3))
    assert await _freshness(client, kb_row["id"]) == ["stale"]
    assert data(await client.get(f"/v1/knowledge-bases/{kb_row['id']}"))["stats"]["stale"] == 1


def test_settings_saved_under_an_old_preset_label_show_the_label_their_steps_match() -> None:
    saved = wire(defaults("file"))["ingest"] | {"preset": "email_templates"}
    assert stored("file", {"ingest": saved}).ingest.preset == "documents"
