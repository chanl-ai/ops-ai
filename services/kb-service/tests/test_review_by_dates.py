"""A document's review-by date and the Changes queue's, by failure mode: a scheduled source's documents showing a
blank review-by beside Fresh or Stale, a stale one dated in the future, and the queue disagreeing with the document
it is about."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.store.knowledge import kb_sources
from ops_store import isolation

from .pdfs import HARDSHIP, policy_pdf
from .test_bases_and_sources import data
from .test_kb_audit_bugs import base_of
from .test_sync import file_source, upload


async def _synced_ago(engine: AsyncEngine, tenant: str, source_id: str, ago: timedelta) -> None:
    at = datetime.now(UTC) - ago
    with isolation.tenant_wide("test: age a source's last sync", tenant_id=tenant):
        async with engine.begin() as c:
            await c.execute(
                sa.update(kb_sources)
                .where(kb_sources.c.tenant_id == tenant, kb_sources.c.id == source_id)
                .values(last_sync_at=at, last_good_sync_at=at)
            )


def _when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


async def _document(client: httpx.AsyncClient, kb_id: str) -> dict[str, str]:
    return data(await client.get(f"/v1/knowledge-bases/{kb_id}/documents"))["data"][0]


async def test_a_documents_review_by_is_the_sources_next_sync_when_fresh_and_the_missed_slot_when_stale(
    engine: AsyncEngine, tenant: str, client: httpx.AsyncClient
) -> None:
    src = await file_source(client)
    await upload(client, src["id"], "hardship.pdf", HARDSHIP)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    kb_row = await base_of(client, src["id"])
    assert (await _document(client, kb_row["id"]))["reviewBy"] == ""  # no schedule: nothing to review against
    slot = (datetime.now(UTC) - timedelta(hours=2)).strftime("%H:%M")
    data(
        await client.patch(f"/v1/sources/{src['id']}", json={"schedule": {"kind": "daily", "time": slot, "tz": "UTC"}})
    )
    await _synced_ago(engine, tenant, src["id"], timedelta(minutes=5))
    fresh = await _document(client, kb_row["id"])
    assert fresh["freshness"] == "fresh" and _when(fresh["reviewBy"]) > datetime.now(UTC), fresh
    await _synced_ago(engine, tenant, src["id"], timedelta(days=3))
    stale = await _document(client, kb_row["id"])
    assert stale["freshness"] == "stale" and _when(stale["reviewBy"]) < datetime.now(UTC), stale


async def test_the_changes_queue_carries_the_same_freshness_and_review_by_as_its_document(
    engine: AsyncEngine, tenant: str, client: httpx.AsyncClient
) -> None:
    src = await file_source(client)
    kb_row = await base_of(client, src["id"])
    await upload(client, src["id"], "rates.pdf", HARDSHIP)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    changed = policy_pdf("Rate Sheet", [("1 Fixed rates", "The five-year fixed mortgage rate is now 5.19 percent.")])
    await upload(client, src["id"], "rates.pdf", changed)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    slot = (datetime.now(UTC) - timedelta(hours=2)).strftime("%H:%M")
    data(
        await client.patch(f"/v1/sources/{src['id']}", json={"schedule": {"kind": "daily", "time": slot, "tz": "UTC"}})
    )
    await _synced_ago(engine, tenant, src["id"], timedelta(days=3))
    [row] = data(await client.get("/v1/knowledge-changes", params={"view": "resolved"}))["data"]
    doc = await _document(client, kb_row["id"])
    assert doc["freshness"] == "stale" and doc["reviewBy"] != "", doc
    assert (row["freshness"], row["reviewBy"]) == (doc["freshness"], doc["reviewBy"]), row
