"""A settings change rebuilds in the background, by failure mode: a save that waits for the rebuild, a rebuild that
reads files again when only splitting changed, a rebuild that cannot be stopped, a sync running beside it, and a
cancel of a run that is not running."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.files import KnowledgeFiles
from ops_kb.service import KnowledgeService
from ops_kb.store import KnowledgeStore
from ops_store import isolation

from .conftest import kb_client
from .pdfs import HARDSHIP, RATES
from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_sync import file_source, upload


class HeldReadings(LocalReadings):
    """Answers each reading only once `release` is set, so a test can act while a rebuild is mid-way."""

    def __init__(self, intake: KnowledgeFiles) -> None:
        super().__init__(intake)
        self.release = asyncio.Event()
        self.release.set()

    async def reading(self, tenant: str, team: str, file_id: str, *, ocr: str) -> dict[str, Any]:
        await self.release.wait()
        return await super().reading(tenant, team, file_id, ocr=ocr)


async def finished(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    for _ in range(200):
        run = data(await client.get(f"/v1/sync-runs/{run_id}"))
        if run["status"] != "running":
            return run
        await asyncio.sleep(0.02)
    raise AssertionError("the rebuild never finished")


def held(engine: AsyncEngine, tenant: str) -> tuple[httpx.AsyncClient, HeldReadings]:
    intake = KnowledgeFiles(Path(mkdtemp(prefix="kb-files-")))
    readings = HeldReadings(intake)
    return kb_client(engine, tenant, files=intake, readings=readings), readings


async def two_files(client: httpx.AsyncClient) -> dict[str, Any]:
    src = await file_source(client)
    await upload(client, src["id"], "hardship.pdf", HARDSHIP)
    await upload(client, src["id"], "rates.pdf", RATES)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    return src


async def test_a_split_change_rebuilds_in_the_background_from_stored_readings(engine: AsyncEngine, tenant: str) -> None:
    client, readings = held(engine, tenant)
    async with client:
        src = await two_files(client)
        reads = len(readings.reads)
        saved = data(
            await client.patch(f"/v1/sources/{src['id']}", json={"ingest": {"strategies": ["fixed"], "size": 150}})
        )
        assert saved["rebuild"] is not None and saved["rebuild"]["trigger"] == "settings", saved["rebuild"]
        run = await finished(client, saved["rebuild"]["id"])
        assert (run["status"], run["counts"]["rebuilt"], run["counts"]["total"]) == ("success", 2, 2), run
        assert run["finishedAt"]
        assert len(readings.reads) == reads, "a split change reads no file again"
        assert data(await client.get(f"/v1/sources/{src['id']}"))["reindexNeeded"] is False
        items = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]
        assert {i["version"] for i in items} == {"v1"}, "a rebuild keeps each item's version"
        unchanged = data(await client.patch(f"/v1/sources/{src['id']}", json={"name": "Renamed"}))
        assert unchanged["rebuild"] is None


async def test_a_running_rebuild_holds_off_a_sync_and_stops_when_cancelled(engine: AsyncEngine, tenant: str) -> None:
    client, readings = held(engine, tenant)
    async with client:
        src = await two_files(client)
        readings.release.clear()
        saved = data(await client.patch(f"/v1/sources/{src['id']}", json={"ingest": {"size": 300}}))
        run_id = saved["rebuild"]["id"]
        busy = await client.post(f"/v1/sources/{src['id']}/sync")
        assert busy.status_code == 409 and busy.json()["error"]["code"] == "sync_running", busy.text
        listed = data(await client.get("/v1/sources"))["data"]
        assert next(s for s in listed if s["id"] == src["id"])["running"] is True
        assert data(await client.post(f"/v1/sync-runs/{run_id}/cancel"))["cancelledBy"]
        readings.release.set()
        run = await finished(client, run_id)
        assert run["status"] == "cancelled" and run["counts"]["checked"] < run["counts"]["total"], run
        again = await client.post(f"/v1/sync-runs/{run_id}/cancel")
        assert again.status_code == 409 and again.json()["error"]["code"] == "run_not_running", again.text
        assert data(await client.get(f"/v1/sources/{src['id']}"))["reindexNeeded"] is True
        assert (await client.post(f"/v1/sources/{src['id']}/sync")).status_code == 200, "the lease is released"


async def test_settings_saved_during_a_rebuild_are_rebuilt_when_it_ends(engine: AsyncEngine, tenant: str) -> None:
    """A save while a rebuild holds the source cannot start its own; without a second rebuild its items would wait for
    the next sync under the old settings (an AI step approved just after a save would write nothing)."""
    client, readings = held(engine, tenant)
    async with client:
        src = await two_files(client)
        readings.release.clear()
        first = data(await client.patch(f"/v1/sources/{src['id']}", json={"ingest": {"size": 300}}))["rebuild"]
        later = data(await client.patch(f"/v1/sources/{src['id']}", json={"ingest": {"size": 500}}))
        assert later["rebuild"] is None, "the running rebuild holds the source"
        readings.release.set()
        await finished(client, first["id"])
        runs: list[dict[str, Any]] = []
        for _ in range(200):
            runs = data(await client.get(f"/v1/sources/{src['id']}/runs"))["data"]
            if len(runs) >= 3 and runs[0]["status"] != "running":
                break
            await asyncio.sleep(0.02)
        assert [r["trigger"] for r in runs[:2]] == ["settings", "settings"], runs
        assert runs[0]["status"] == "success" and runs[0]["counts"]["rebuilt"] == 2, runs[0]
        assert data(await client.get(f"/v1/sources/{src['id']}"))["reindexNeeded"] is False


async def test_a_rebuild_longer_than_its_lease_never_overlaps_a_sync_and_is_not_ended_as_stale(
    engine: AsyncEngine, tenant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lease was taken once for 15 minutes and never renewed: a 20-minute rebuild lost it, a sync ran beside it,
    the stale sweep ended it as stopped, and its release then cleared the lease the sync held. A rebuild seen finished
    must also have freed its source: the work after it (embedding the new pieces) is slowed here to show any gap."""
    monkeypatch.setattr("ops_kb.service.LEASE", timedelta(seconds=0.3))
    embed_now = KnowledgeService.embed_now

    async def slow_embed(self: KnowledgeService, tenant: str) -> int:
        await asyncio.sleep(0.5)
        return await embed_now(self, tenant)

    monkeypatch.setattr(KnowledgeService, "embed_now", slow_embed)
    client, readings = held(engine, tenant)
    store = KnowledgeStore(engine)
    async with client:
        src = await two_files(client)
        readings.release.clear()
        rebuild = data(await client.patch(f"/v1/sources/{src['id']}", json={"ingest": {"size": 300}}))["rebuild"]
        for _ in range(4):
            # Several leases' worth of time: the running rebuild keeps renewing its own.
            await asyncio.sleep(0.3)
            busy = await client.post(f"/v1/sources/{src['id']}/sync")
            assert busy.status_code == 409 and busy.json()["error"]["code"] == "sync_running", busy.text
            with isolation.tenant_wide("test: the stale-run sweep", tenant_id=tenant):
                assert await store.end_stale_runs(tenant, reason="stopped") == 0
        readings.release.set()
        run = await finished(client, rebuild["id"])
        assert run["status"] == "success", run
        assert (await client.post(f"/v1/sources/{src['id']}/sync")).status_code == 200


async def test_a_lease_is_released_only_by_its_holder(engine: AsyncEngine, tenant: str) -> None:
    client, _ = held(engine, tenant)
    store = KnowledgeStore(engine)
    async with client:
        src = await two_files(client)
    with isolation.tenant_wide("test: two holders of one lease", tenant_id=tenant):
        assert await store.claim(tenant, src["id"], owner="lease_a", seconds=0.01)
        await asyncio.sleep(0.05)
        assert await store.claim(tenant, src["id"], owner="lease_b", seconds=60), "a lapsed lease is taken over"
        await store.release(tenant, src["id"], owner="lease_a")
        assert not await store.claim(tenant, src["id"], owner="lease_c", seconds=60), "a's release left b's lease"
        assert not await store.renew(tenant, src["id"], owner="lease_a", seconds=60)
