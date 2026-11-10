"""The SharePoint and Confluence plugins on kb-service's one sync path, by failure mode: a connector's items not
indexed or not kept as snapshot files, a second sync fetching what did not change, a change at the source not found
through its changes tool, a delete at the source left in search, who-can-see dropped, and the pickers not reaching the
plugin's scopes tool. The plugins' own code runs through the plugin SDK's runner against each plugin's fake system,
standing in for tools-service, so kb-service and the plugin meet on the contract as they do in a stack.

Needs the plugins checkout holding plugins/sharepoint and plugins/confluence (OPS_PLUGINS_REPO, else ../ops-ai-plugins
beside this checkout); skipped without it."""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth
from ops_kb.agents import StaticAgents
from ops_kb.app import create_kb_app
from ops_kb.files import KnowledgeFiles
from ops_kb.tool_sources import Answer
from ops_plugin_sdk import PluginError
from ops_plugin_sdk.testing import Fake, call
from ops_service_kit.settings import Settings

from .readings_fake import LocalReadings
from .test_bases_and_sources import data

PLUGINS = Path(os.environ.get("OPS_PLUGINS_REPO") or Path(__file__).parents[4] / "ops-ai-plugins") / "plugins"


def load(name: str) -> tuple[Any, Any]:
    """The plugin module and its tests' fake system module."""
    root = PLUGINS / name
    if not (root / "src").is_dir():
        pytest.skip(f"no {name} plugin at {root}")
    for p in (root / "src", root / "tests"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    return importlib.import_module(f"ops_plugin_{name}"), importlib.import_module(
        "fake_graph" if name == "sharepoint" else "fake_confluence"
    )


class PluginReader:
    """tools-service's part for one team: the plugin declared with a working team connection, and each call run by
    the SDK's runner on the fake system."""

    def __init__(self, plugin: Any, source: str, settings: dict[str, Any], system: Callable[..., httpx.Response]):
        self.plugin, self.settings = plugin, settings
        self.fake = Fake(httpx.Client(transport=httpx.MockTransport(system)), "tok")
        self.ks = next(s for s in plugin.manifest.knowledge_sources if s.name == source)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def source_hosts(self, *_: Any, **__: Any) -> list[dict[str, Any]]:
        return []

    async def declared(self, tenant_id: str, team_id: str) -> list[dict[str, Any]]:
        ks, m = self.ks, self.plugin.manifest
        return [
            {
                "plugin": m.id, "source": ks.name, "title": ks.title, "listTool": ks.list, "getTool": ks.get,
                "changesTool": ks.changes, "scopesTool": ks.scopes, "deletedTool": ks.deleted, "previewTool": None,
                "listsWhole": ks.lists_whole, "fetchAtOnce": ks.fetch_at_once, "site": ks.site,
                "inputs": {k: f.model_dump(exclude_none=True) for k, f in ks.inputs.items()},
                "getTakesTag": True, "needsConnection": True, "schedule": ks.schedule.model_dump(),
                "connectionId": "con_team", "signIn": "team", "connectionStatus": "healthy",
            }
        ]  # fmt: skip

    async def call(self, tenant_id: str, team_id: str, tool: str, args: dict[str, Any], *, act: str) -> Answer:
        self.calls.append((tool, dict(args)))
        try:
            return Answer(True, call(self.plugin, tool, args, self.settings, self.fake))
        except PluginError as e:
            return Answer(False, code=str(getattr(e, "code", "refused")), message=str(e))

    def fetched(self) -> list[str]:
        return [str(a["id"]) for t, a in self.calls if t == self.ks.get]


async def kb_on(engine: AsyncEngine, tenant: str, reader: PluginReader, tmp: Path) -> AsyncIterator[httpx.AsyncClient]:
    auth = Auth.for_dev(Settings(), audience="kb", name="james", email="james@harborpine.example", tenant_id=tenant)
    files = KnowledgeFiles(tmp)
    app = create_kb_app(
        engine, auth=auth, files=files, agents=StaticAgents(), tools=reader,  # type: ignore[arg-type]
        readings=LocalReadings(files), schedule=False,
    )  # fmt: skip
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kb") as c:
        yield c


async def made(kb: httpx.AsyncClient, reader: PluginReader, values: dict[str, Any]) -> tuple[str, str]:
    base = data(
        await kb.post("/v1/knowledge-bases", json={"name": "Policies", "owner": "james@harborpine.example"}), 201
    )
    m = reader.plugin.manifest
    body = {"type": "tool", "name": m.display.description[:40] or m.id, "kbIds": [base["id"]],
            "config": {"plugin": m.id, "source": reader.ks.name, "values": values}}  # fmt: skip
    src = data(await kb.post("/v1/sources", json=body), 201)
    return str(base["id"]), str(src["id"])


async def items(kb: httpx.AsyncClient, source_id: str) -> dict[str, dict[str, Any]]:
    rows = data(await kb.get(f"/v1/sources/{source_id}/items?pageSize=100"))["data"]
    return {str(r["path"]): r for r in rows}


async def search(kb: httpx.AsyncClient, kb_id: str, question: str) -> list[dict[str, Any]]:
    found = data(await kb.post("/v1/knowledge-bases/search", json={"kbIds": [kb_id], "question": question}))
    return list(found["passages"])


@pytest.fixture
async def sharepoint(engine: AsyncEngine, tenant: str, tmp_path: Path) -> AsyncIterator[tuple[Any, Any, Any]]:
    mod, fakes = load("sharepoint")
    graph = fakes.FakeGraph()
    reader = PluginReader(mod.plugin, "files", {"sharepoint_url": fakes.SHAREPOINT}, graph)
    async for kb in kb_on(engine, tenant, reader, tmp_path):
        yield kb, reader, (graph, fakes)


async def test_sharepoint_files_sync_once_change_by_delta_and_leave_when_deleted(sharepoint: Any) -> None:
    kb, reader, (graph, fakes) = sharepoint
    kb_id, src = await made(kb, reader, {"sites": [fakes.SITE_HR]})
    run1 = data(await kb.post(f"/v1/sources/{src}/sync", json={}))
    first = await items(kb, src)
    leave = next(
        (r for k, r in first.items() if k.endswith(":p1")),
        {"debug": {k: (r["status"], r.get("error")) for k, r in first.items()}, "runs": reader.calls[:3]},
    )
    assert leave.get("status") == "indexed" and leave.get("fileId"), (leave, run1)
    assert any("Twenty days" in p["text"] for p in await search(kb, kb_id, "leave days a year"))
    before = len(reader.fetched())
    graph.edit(fakes.LIB_POLICIES, "p2", b"Claim within 14 days.\n")
    graph.remove(fakes.LIB_POLICIES, "p1")
    run = data(await kb.post(f"/v1/sources/{src}/sync", json={}))
    again = reader.fetched()[before:]
    assert [i.split(":")[-1] for i in again] == ["p2"], (again, run["counts"])
    assert any("14 days" in p["text"] for p in await search(kb, kb_id, "claim expenses within days"))
    assert not any("Twenty days" in p["text"] for p in await search(kb, kb_id, "leave days a year"))


async def test_sharepoint_pickers_reach_the_plugins_scopes_tool(sharepoint: Any) -> None:
    kb, reader, (_, fakes) = sharepoint
    m = reader.plugin.manifest.id
    sites = data(await kb.post("/v1/sources/scopes", json={"plugin": m, "source": "files", "query": "human"}))
    assert [(s["id"], s["kind"]) for s in sites["scopes"]] == [(fakes.SITE_HR, "site")], sites
    libraries = data(
        await kb.post("/v1/sources/scopes", json={"plugin": m, "source": "files", "parent": fakes.SITE_HR})
    )
    assert {s["id"] for s in libraries["scopes"]} == {fakes.LIB_POLICIES, fakes.LIB_HANDBOOK}, libraries
    assert all(s["kind"] == "library" and s["parent"] == fakes.SITE_HR for s in libraries["scopes"])


async def test_confluence_pages_sync_and_an_edit_is_the_only_page_fetched_again(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    mod, fakes = load("confluence")
    site = fakes.FakeConfluence()
    reader = PluginReader(mod.plugin, "spaces", {"site_url": site.site_url}, site)
    async for kb in kb_on(engine, tenant, reader, tmp_path):
        kb_id, src = await made(kb, reader, {"spaces": ["ENG"]})
        data(await kb.post(f"/v1/sources/{src}/sync", json={}))
        first = await items(kb, src)
        assert first and all(r["status"] == "indexed" for r in first.values()), first
        assert any("pipeline" in p["text"] for p in await search(kb, kb_id, "deploy pipeline"))
        before = len(reader.fetched())
        site.edit("101", "<p>Deploy with the release train.</p>")
        data(await kb.post(f"/v1/sources/{src}/sync", json={}))
        assert reader.fetched()[before:] == ["101"], reader.fetched()[before:]
        assert any("release train" in p["text"] for p in await search(kb, kb_id, "deploy release train"))
