"""Knowledge bases and file sources (c-056 T002), by failure mode: a knowledge base nobody owns, another tenant's
knowledge reachable, names the console shows not joined, a source type the slice cannot sync accepted, a list the
console cannot page or search, and a removed source still listed on its knowledge base."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from .conftest import kb_client

POLICIES = {"name": "Lending policies", "owner": "maya@harborpine.example", "description": "Mortgage rules"}


def data(r: httpx.Response, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


async def source(client: httpx.AsyncClient, name: str = "Policy PDFs", **extra: Any) -> dict[str, Any]:
    body = {"type": "file", "name": name, "collection": "Lending", **extra}
    return data(await client.post("/v1/sources", json=body), 201)


async def test_a_knowledge_base_needs_an_owner(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/knowledge-bases", json={"name": "Lending policies"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "collection_without_owner", r.text
    kb = data(await client.post("/v1/knowledge-bases", json=POLICIES), 201)
    assert (kb["owner"], kb["health"], kb["retrieval"]["searchMode"]) == ("maya@harborpine.example", "never", "keyword")
    again = await client.post("/v1/knowledge-bases", json={**POLICIES, "name": "lending POLICIES"})
    assert again.status_code == 409, again.text


async def test_another_tenants_knowledge_is_not_reachable(engine: AsyncEngine, client: httpx.AsyncClient) -> None:
    kb = data(await client.post("/v1/knowledge-bases", json=POLICIES), 201)
    src = await source(client)
    async with kb_client(engine, "t_other") as other:
        assert (await other.get(f"/v1/knowledge-bases/{kb['id']}")).status_code == 404
        assert (await other.get(f"/v1/sources/{src['id']}")).status_code == 404
        assert data(await other.get("/v1/knowledge-bases"))["data"] == []
        assert (await other.delete(f"/v1/sources/{src['id']}")).status_code == 404


async def test_lists_and_details_join_the_names_the_console_shows(client: httpx.AsyncClient) -> None:
    src = await source(client)
    mine = {**POLICIES, "owner": "james@harborpine.example", "sourceIds": [src["id"]]}
    kb = data(await client.post("/v1/knowledge-bases", json=mine), 201)
    row = data(await client.get("/v1/knowledge-bases"))["data"][0]
    assert (row["id"], row["sourceNames"]) == (kb["id"], ["Policy PDFs"])
    detail = data(await client.get(f"/v1/knowledge-bases/{kb['id']}"))
    assert [a["source"]["name"] for a in detail["attached"]] == ["Policy PDFs"]
    listed = data(await client.get("/v1/sources"))["data"][0]
    assert listed["usedBy"] == [{"id": kb["id"], "name": "Lending policies"}]
    readers = data(await client.get(f"/v1/sources/{src['id']}"))["readers"]
    assert [r["name"] for r in readers] == ["Lending policies"]
    unknown = await client.post(f"/v1/knowledge-bases/{kb['id']}/sources", json={"sourceIds": ["src_nope"]})
    assert unknown.status_code == 404, unknown.text


async def test_only_file_sources_are_accepted(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/sources", json={"type": "sharepoint", "name": "Intranet"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "type_unsupported_in_phase", r.text


async def test_lists_page_search_and_count_facets(client: httpx.AsyncClient) -> None:
    for name in ("Rates", "Hardship", "Mortgages"):
        await source(client, name)
    first = data(await client.get("/v1/sources", params={"page": 1, "pageSize": 2}))
    second = data(await client.get("/v1/sources", params={"page": 2, "pageSize": 2}))
    assert (first["pagination"]["total"], first["pagination"]["hasNext"], len(second["data"])) == (3, True, 1)
    assert {r["name"] for r in first["data"] + second["data"]} == {"Rates", "Hardship", "Mortgages"}
    found = data(await client.get("/v1/sources", params={"search": "hard"}))
    assert [r["name"] for r in found["data"]] == ["Hardship"]
    assert first["facets"]["type"] == {"file": 3}


async def test_a_removed_source_leaves_its_knowledge_bases(client: httpx.AsyncClient) -> None:
    src = await source(client)
    kb = data(await client.post("/v1/knowledge-bases", json={**POLICIES, "sourceIds": [src["id"]]}), 201)
    assert (await client.delete(f"/v1/sources/{src['id']}")).status_code == 204
    detail = data(await client.get(f"/v1/knowledge-bases/{kb['id']}"))
    assert (detail["attached"], detail["sources"]) == ([], [])
