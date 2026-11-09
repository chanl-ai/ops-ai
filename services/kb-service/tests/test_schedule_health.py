"""One scheduler, health and deletes, by failure mode: a file source with a schedule never synced on its own, a
paused or manual one synced anyway, a bad schedule saved, a failing source shown healthy or never alerted (or alerted
every run), and a page gone at its source removed on one miss, kept for ever, or brought back by a link before its
tombstone is lifted."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, ServiceClient, dev_service_signer
from ops_kb.agents import StaticAgents
from ops_kb.app import create_kb_app
from ops_kb.files import KnowledgeFiles
from ops_kb.schedule import run_due
from ops_kb.service import KnowledgeService
from ops_kb.store import KnowledgeStore
from ops_kb.store.event_relay import relay
from ops_kb.store.fulltext import PostgresFullTextRetriever
from ops_kb.tool_sources import Answer
from ops_service_kit.settings import Settings
from ops_store import isolation

from .conftest import kb_client
from .pdfs import HARDSHIP
from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_sync import file_source, upload
from .test_web_source import SITE, WebPlugin


async def test_a_scheduled_file_source_syncs_on_its_own_and_a_manual_or_paused_one_does_not(
    engine: AsyncEngine, tenant: str
) -> None:
    intake = KnowledgeFiles(Path(mkdtemp(prefix="kb-files-")))
    async with kb_client(engine, tenant, files=intake, readings=LocalReadings(intake)) as client:
        hourly = await file_source(client)
        data(await client.patch(f"/v1/sources/{hourly['id']}", json={"schedule": {"kind": "hourly", "every": 1}}))
        await upload(client, hourly["id"], "hardship.pdf", HARDSHIP)
        manual = await file_source(client)
        paused = await file_source(client)
        data(await client.patch(f"/v1/sources/{paused['id']}", json={"schedule": {"kind": "hourly", "every": 1}}))
        data(await client.post(f"/v1/sources/{paused['id']}/pause"))
        bad = await client.patch(f"/v1/sources/{manual['id']}", json={"schedule": {"kind": "hourly", "every": 3}})
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_settings", bad.text
        shown = data(await client.get(f"/v1/sources/{hourly['id']}"))
        assert shown["schedule"] == {"kind": "hourly", "every": 1} and shown["nextSyncAt"], shown
        service = KnowledgeService(KnowledgeStore(engine), intake, PostgresFullTextRetriever(engine), StaticAgents(),
                                   readings=LocalReadings(intake))  # fmt: skip
        with isolation.tenant_wide("test: the schedule as its background process", tenant_id=tenant):
            ran = await run_due(service, datetime.now(UTC))
        mine = {hourly["id"], manual["id"], paused["id"]}
        assert [r for r in ran if r in mine] == [hourly["id"]], ran
        run = data(await client.get(f"/v1/sources/{hourly['id']}/runs"))["data"][0]
        assert (run["trigger"], run["counts"]["upserted"]) == ("schedule", 1), run
        assert data(await client.get(f"/v1/sources/{hourly['id']}"))["health"]["state"] == "healthy"


class Agents:
    """agents-service's POST /v1/events as kb-service's relay calls it."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def client(self) -> ServiceClient:
        def handle(request: httpx.Request) -> httpx.Response:
            self.events.append(json.loads(request.content))
            return httpx.Response(202, json={"success": True, "data": {"name": "x", "status": "unhandled"}})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://agents")
        return ServiceClient(http, dev_service_signer(), "kb", "agents", ["events:emit"])


@pytest.fixture
def web() -> WebPlugin:
    return WebPlugin()


@pytest.fixture
async def kb(engine: AsyncEngine, tenant: str, web: WebPlugin, tmp_path: Any) -> AsyncIterator[httpx.AsyncClient]:
    auth = Auth.for_dev(Settings(), audience="kb", name="james", email="james@harborpine.example", tenant_id=tenant)
    files = KnowledgeFiles(tmp_path)
    app = create_kb_app(engine, auth=auth, files=files, agents=StaticAgents(), tools=web,  # type: ignore[arg-type]
                        readings=LocalReadings(files), schedule=False)  # fmt: skip
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kb") as c:
        yield c


async def site(kb: httpx.AsyncClient) -> dict[str, Any]:
    body = {
        "type": "tool",
        "name": "Help",
        "config": {"plugin": "opsai.web", "source": "site", "values": {"start": [f"{SITE}/"]}},
    }
    return data(await kb.post("/v1/sources", json=body), 201)


async def test_a_failing_source_shows_it_and_alerts_once_on_its_second_failure(
    engine: AsyncEngine, kb: httpx.AsyncClient, web: WebPlugin
) -> None:
    src = await site(kb)
    assert data(await kb.post(f"/v1/sources/{src['id']}/sync"))["status"] == "success"
    real = web.call

    async def broken(tenant_id: str, team_id: str, tool: str, args: dict[str, Any], *, act: str) -> Answer:
        if tool.endswith("list_pages"):
            return Answer(False, code="UPSTREAM_UNREACHABLE", message="help.northbank.test did not answer")
        return await real(tenant_id, team_id, tool, args, act=act)

    web.call = broken  # type: ignore[method-assign]
    for _ in range(3):
        assert data(await kb.post(f"/v1/sources/{src['id']}/sync"))["status"] == "failed"
    health = data(await kb.get(f"/v1/sources/{src['id']}"))["health"]
    assert (health["state"], health["failedRuns"], health["daysFailing"]) == ("failing", 3, 0), health
    assert health["lastGoodSyncAt"] and health["failingSince"]
    agents = Agents()
    await relay(engine, None, agents.client()).once()
    mine = [e for e in agents.events if e["payload"].get("sourceId") == src["id"]]
    assert [(e["name"], e["payload"]["failedRuns"]) for e in mine] == [("knowledge.source.failing", 2)], mine
    web.call = real  # type: ignore[method-assign]
    assert data(await kb.post(f"/v1/sources/{src['id']}/sync"))["status"] == "success"
    assert data(await kb.get(f"/v1/sources/{src['id']}"))["health"]["state"] == "healthy"


async def test_a_page_gone_twice_is_removed_tombstoned_and_back_only_once_lifted(
    kb: httpx.AsyncClient, web: WebPlugin
) -> None:
    src = await site(kb)
    gone = f"{SITE}/lending/fees"
    await kb.post(f"/v1/sources/{src['id']}/sync")
    body = web.pages[gone]
    web.pages[gone] = body + " "  # its listing moves, so it is fetched, and then it answers gone
    real = web.call

    async def missing(tenant_id: str, team_id: str, tool: str, args: dict[str, Any], *, act: str) -> Answer:
        if tool.endswith("get_page") and args.get("id") == gone:
            return Answer(False, code="NOT_FOUND", message=f"{gone} answered 404.")
        return await real(tenant_id, team_id, tool, args, act=act)

    web.call = missing  # type: ignore[method-assign]
    first = data(await kb.post(f"/v1/sources/{src['id']}/sync"))
    titles = {i["path"] for i in data(await kb.get(f"/v1/sources/{src['id']}/items"))["data"]}
    assert gone in titles and first["counts"]["deleted"] == 0, "one miss removes nothing"
    second = data(await kb.post(f"/v1/sources/{src['id']}/sync"))
    assert second["counts"]["deleted"] == 1, second
    assert [t["id"] for t in data(await kb.get(f"/v1/sources/{src['id']}/tombstones"))] == [gone]
    web.call = real  # type: ignore[method-assign]
    third = data(await kb.post(f"/v1/sources/{src['id']}/sync"))
    assert gone not in {i["path"] for i in data(await kb.get(f"/v1/sources/{src['id']}/items"))["data"]}, third
    data(await kb.post(f"/v1/sources/{src['id']}/tombstones/lift", json={"ids": [gone]}))
    data(await kb.post(f"/v1/sources/{src['id']}/sync"))
    assert gone in {i["path"] for i in data(await kb.get(f"/v1/sources/{src['id']}/items"))["data"]}
    assert data(await kb.get(f"/v1/sources/{src['id']}"))["health"]["tombstoned"] == 0
