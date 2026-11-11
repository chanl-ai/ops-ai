"""kb-service on the knowledge-source contract v2, by failure mode: a source's own settings never checked or never
sent, an incremental run that lists everything though the plugin has a changes tool, an item the system deleted
staying in search, an unchanged item fetched and versioned again, and the folder, fields and allowed ids a fetch gives
being dropped."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth
from ops_kb.agents import StaticAgents
from ops_kb.app import create_kb_app
from ops_kb.files import KnowledgeFiles
from ops_kb.tool_sources import Answer
from ops_service_kit.settings import Settings

from .readings_fake import LocalReadings
from .test_bases_and_sources import data

LIST, GET, CHANGES = "wiki_list_pages", "wiki_get_page", "wiki_changed_pages"


class Wiki:
    """A wiki's plugin as tools-service runs it: pages in one space, a changes tool with a cursor, and ETag tags."""

    def __init__(self) -> None:
        self.pages: dict[str, dict[str, Any]] = {
            "p1": {"title": "Escrow", "body": "<h1>Escrow</h1><p>Escrow is analysed every year.</p>", "v": 1},
            "p2": {"title": "Late fees", "body": "<h1>Late fees</h1><p>Four percent after fifteen days.</p>", "v": 1},
        }
        self.deleted: list[str] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def source_hosts(self, tenant_id: str, team_id: str, cfg: dict[str, Any], **_: Any) -> list[dict[str, Any]]:
        return []

    async def declared(self, tenant_id: str, team_id: str) -> list[dict[str, Any]]:
        return [
            {
                "plugin": "opsai.wiki", "source": "space", "title": "Wiki space", "listTool": LIST, "getTool": GET,
                "changesTool": CHANGES, "getTakesTag": True, "deletedTool": None,
                "inputs": {"space": {"type": "string"}, "labels": {"type": "array", "required": False}},
                "schedule": {"kind": "daily", "time": "02:00"}, "connectionId": "con_wiki", "signIn": "team",
                "connectionStatus": "healthy",
            }
        ]  # fmt: skip

    def _row(self, k: str) -> dict[str, Any]:
        v = self.pages[k]
        return {"id": k, "title": v["title"], "updated_at": f"2026-11-0{v['v']}T00:00:00Z"}

    async def call(self, tenant_id: str, team_id: str, tool: str, args: dict[str, Any], *, act: str) -> Answer:
        self.calls.append((tool, dict(args)))
        if tool == LIST:
            return Answer(True, {"items": [self._row(k) for k in self.pages], "cursor": "c1"})
        if tool == CHANGES:
            assert args.get("cursor") == "c1", args
            rows = [self._row(k) for k, v in self.pages.items() if v["v"] > 1]
            rows += [{"id": k, "updated_at": "2026-11-09T00:00:00Z", "deleted": True} for k in self.deleted]
            return Answer(True, {"items": rows, "cursor": "c1"})
        page = self.pages[str(args["id"])]
        etag = f"etag-{args['id']}-{len(page['body'])}"
        if args.get("tag") == etag:
            return Answer(True, {"unchanged": True})
        return Answer(
            True,
            {
                "id": args["id"], "title": page["title"], "mime": "text/html", "content": page["body"],
                "marker": etag, "url": f"https://wiki.test/{args['id']}", "folder": "Servicing / Fees",
                "metadata": {"Dept": "Mortgage servicing"}, "allowed": ["group:servicing", "user:7"],
            },
        )  # fmt: skip

    def got(self) -> list[str]:
        return [str(a["id"]) for t, a in self.calls if t == GET]


@pytest.fixture
def wiki() -> Wiki:
    return Wiki()


@pytest.fixture
async def kb(engine: AsyncEngine, tenant: str, wiki: Wiki, tmp_path: Any) -> AsyncIterator[httpx.AsyncClient]:
    auth = Auth.for_dev(Settings(), audience="kb", name="james", email="james@harborpine.example", tenant_id=tenant)
    files = KnowledgeFiles(tmp_path)
    app = create_kb_app(
        engine, auth=auth, files=files, agents=StaticAgents(), tools=wiki,  # type: ignore[arg-type]
        readings=LocalReadings(files), schedule=False,
    )  # fmt: skip
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kb") as c:
        yield c


async def space(kb: httpx.AsyncClient, values: dict[str, Any] | None = None) -> httpx.Response:
    body = {
        "type": "tool",
        "name": "Servicing wiki",
        "config": {"plugin": "opsai.wiki", "source": "space", "values": values or {"space": "SERV"}},
        "metadataMapping": [{"key": "department_detail", "from": "field:Dept"}],
    }
    return await kb.post("/v1/sources", json=body)


async def sync(kb: httpx.AsyncClient, source_id: str, *, full: bool = False) -> dict[str, Any]:
    return data(await kb.post(f"/v1/sources/{source_id}/sync", json={"full": full}))


async def test_a_sources_values_are_checked_and_sent_to_every_call(kb: httpx.AsyncClient, wiki: Wiki) -> None:
    missing = await space(kb, {"labels": ["fees"]})
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "invalid_source_values", missing.text
    unknown = await space(kb, {"space": "SERV", "sites": ["x"]})
    assert unknown.status_code == 400 and "takes no sites" in unknown.json()["error"]["message"], unknown.text
    src = data(await space(kb), 201)
    await sync(kb, src["id"])
    assert wiki.calls and all(a.get("source") == {"space": "SERV"} for _, a in wiki.calls), wiki.calls


async def test_an_incremental_run_lists_changes_and_takes_a_deleted_page_out(kb: httpx.AsyncClient, wiki: Wiki) -> None:
    src = data(await space(kb), 201)
    kb_row = data(
        await kb.post(
            "/v1/knowledge-bases",
            json={"name": "Servicing", "owner": "james@harborpine.example", "sourceIds": [src["id"]]},
        ),
        201,
    )
    await sync(kb, src["id"])
    wiki.pages["p2"] |= {"v": 2, "body": "<h1>Late fees</h1><p>Five percent after ten days.</p>"}
    wiki.deleted.append("p1")
    wiki.calls.clear()
    run = await sync(kb, src["id"])
    assert [t for t, _ in wiki.calls if t != GET] == [CHANGES], wiki.calls
    assert (run["counts"]["upserted"], run["counts"]["deleted"]) == (1, 1), run
    titles = {i["title"]: i for i in data(await kb.get(f"/v1/sources/{src['id']}/items"))["data"]}
    assert set(titles) == {"Late fees"} and titles["Late fees"]["version"] == "v2"
    found = data(
        await kb.post(
            "/v1/knowledge-bases/search", json={"kbIds": [kb_row["id"]], "question": "escrow analysed every year"}
        )
    )
    assert found["passages"] == [], found


async def test_an_unchanged_page_answers_to_its_tag_and_is_not_versioned_again(
    kb: httpx.AsyncClient, wiki: Wiki
) -> None:
    src = data(await space(kb), 201)
    await sync(kb, src["id"])
    wiki.pages["p1"]["v"] = 3  # touched at the source: a new time, the same text
    wiki.calls.clear()
    run = await sync(kb, src["id"], full=True)
    assert [a.get("tag") for t, a in wiki.calls if t == GET] == ["etag-p1-52"], wiki.calls
    assert (run["counts"]["upserted"], run["counts"]["unchanged"]) == (0, 2), run
    assert {i["version"] for i in data(await kb.get(f"/v1/sources/{src['id']}/items"))["data"]} == {"v1"}


async def test_folder_fields_and_allowed_ids_are_kept(kb: httpx.AsyncClient, wiki: Wiki) -> None:
    src = data(await space(kb), 201)
    await sync(kb, src["id"])
    [item] = [i for i in data(await kb.get(f"/v1/sources/{src['id']}/items"))["data"] if i["title"] == "Escrow"]
    assert item["folder"] == "Servicing / Fees"
    detail = data(await kb.get(f"/v1/items/{item['id']}"))
    assert detail["detail"]["versions"][0]["allowed"] == ["group:servicing", "user:7"]
    assert all(c["metadata"]["department_detail"] == "Mortgage servicing" for c in detail["detail"]["chunks"])


async def test_a_kind_of_source_with_no_pickers_refuses_a_scopes_search(kb: httpx.AsyncClient) -> None:
    refused = await kb.post("/v1/sources/scopes", json={"plugin": "opsai.wiki", "source": "space", "query": "serv"})
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "scopes_unavailable", refused.text
