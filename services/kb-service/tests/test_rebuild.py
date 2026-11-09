"""A settings change rebuilds in the background, by failure mode: a save that waits for the rebuild, a rebuild that
reads files again when only splitting changed, a rebuild that cannot be stopped, a sync running beside it, and a
cancel of a run that is not running."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.files import KnowledgeFiles

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
