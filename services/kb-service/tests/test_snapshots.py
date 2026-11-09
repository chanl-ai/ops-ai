"""Every fetched item kept as a file, by failure mode: a rebuild that fetches from the system again, a citation that
cannot open the copy it came from, and an old copy kept for ever once a newer one or a delete replaces it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_files_client import Purpose
from ops_identity import Auth
from ops_kb.agents import StaticAgents
from ops_kb.app import create_kb_app
from ops_kb.files import KnowledgeFiles, Stored
from ops_service_kit.settings import Settings

from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_rebuild import finished
from .test_tool_sources import FakeTools, source, sync


class Snapshots(KnowledgeFiles):
    """The local file store, recording each purpose stored and each file a source let go."""

    def __init__(self) -> None:
        super().__init__(Path(mkdtemp(prefix="kb-files-")))
        self.purposes: dict[str, str] = {}
        self.released: list[str] = []

    async def put(
        self,
        tenant: str,
        team: str,
        data: bytes,
        *,
        name: str,
        mime: str,
        actor: str,
        purpose: Purpose = "knowledge_source",
    ) -> Stored:
        stored = await super().put(tenant, team, data, name=name, mime=mime, actor=actor, purpose=purpose)
        self.purposes[stored.file_id] = purpose
        return stored

    async def release(self, tenant: str, team: str, file_id: str, *, source_id: str) -> None:
        self.released.append(file_id)


@pytest.fixture
def snapshots() -> Snapshots:
    return Snapshots()


@pytest.fixture
async def kb(
    engine: AsyncEngine, tenant: str, tools: FakeTools, snapshots: Snapshots
) -> AsyncIterator[httpx.AsyncClient]:
    auth = Auth.for_dev(Settings(), audience="kb", name="james", email="james@harborpine.example", tenant_id=tenant)
    app = create_kb_app(
        engine,
        auth=auth,
        files=snapshots,
        agents=StaticAgents(),
        tools=tools,  # type: ignore[arg-type]
        readings=LocalReadings(snapshots),
        schedule=False,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kb") as c:
        yield c


@pytest.fixture
def tools() -> FakeTools:
    return FakeTools()


async def items(kb: httpx.AsyncClient, source_id: str) -> dict[str, dict[str, Any]]:
    return {i["title"]: i for i in data(await kb.get(f"/v1/sources/{source_id}/items"))["data"]}


async def test_each_fetched_item_is_a_snapshot_a_rebuild_reads_with_no_fetch(
    kb: httpx.AsyncClient, tools: FakeTools, snapshots: Snapshots
) -> None:
    src = await source(kb)
    assert (await sync(kb, src["id"]))["counts"]["upserted"] == 4
    held = await items(kb, src["id"])
    assert all(i["fileId"] and snapshots.purposes[i["fileId"]] == "knowledge_snapshot" for i in held.values()), held
    tools.calls.clear()
    saved = data(await kb.patch(f"/v1/sources/{src['id']}", json={"ingest": {"strategies": ["fixed"], "size": 120}}))
    run = await finished(kb, saved["rebuild"]["id"])
    assert (run["status"], run["counts"]["rebuilt"]) == ("success", 4), run
    assert tools.calls == [], "a rebuild reads the snapshots and calls the system for nothing"


async def test_a_citation_names_the_snapshot_and_the_address_it_came_from(kb: httpx.AsyncClient) -> None:
    src = await source(kb)
    base = {"name": "Cards", "owner": "james@harborpine.example", "sourceIds": [src["id"]]}
    kb_row = data(await kb.post("/v1/knowledge-bases", json=base), 201)
    await sync(kb, src["id"])
    found = data(
        await kb.post("/v1/knowledge-bases/search", json={"kbIds": [kb_row["id"]], "question": "block lost card"})
    )
    [passage] = [p for p in found["passages"] if p["title"] == "Report a lost card"]
    item = (await items(kb, src["id"]))["Report a lost card"]
    assert (passage["fileId"], passage["url"]) == (item["fileId"], "https://acme/ka2"), passage


async def test_an_older_or_deleted_items_snapshot_is_let_go(
    kb: httpx.AsyncClient, tools: FakeTools, snapshots: Snapshots
) -> None:
    src = await source(kb)
    await sync(kb, src["id"])
    before = await items(kb, src["id"])
    tools.articles["ka2"] |= {"updated_at": "2026-10-09T09:00:00Z", "body": "<p>Block it in the app at once.</p>"}
    await sync(kb, src["id"])
    after = await items(kb, src["id"])
    assert after["Report a lost card"]["version"] == "v2"
    assert after["Report a lost card"]["fileId"] != before["Report a lost card"]["fileId"]
    assert snapshots.released == [before["Report a lost card"]["fileId"]]
    del tools.articles["ka3"]
    await sync(kb, src["id"], full=True)
    assert before["Travel notices"]["fileId"] in snapshots.released
