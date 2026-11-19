"""The Documents table and the Test sheet, by failure mode: a filter the console sends that the list drops, so every
document shows under any chip; facets that count only the page shown; and a Test question narrowed to one collection
that still cites another."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from .conftest import kb_client
from .test_bases_and_sources import data

RULE = "A card dispute must be raised within 120 days of the statement date that first shows the charge."


@pytest.fixture
async def client(engine: AsyncEngine, tenant: str) -> AsyncIterator[httpx.AsyncClient]:
    async with kb_client(engine, tenant) as c:
        yield c


async def library(client: httpx.AsyncClient) -> str:
    body = {"name": "Policy library", "owner": "w.kamau@harborpine.example", "retrieval": {"searchMode": "keyword"}}
    kb = str(data(await client.post("/v1/knowledge-bases", json=body), 201)["id"])
    for collection, items in {
        "Cards": [
            ("Dispute limits", "text/markdown", None),
            ("Lost card", "text/html", "https://bank.example/lost-card"),
        ],
        "Compliance": [("Complaints policy", "text/markdown", None)],
    }.items():
        src = data(
            await client.post(
                "/v1/sources",
                json={"type": "push", "name": f"{collection} feed", "kbIds": [kb], "collection": collection},
            ),
            201,
        )
        for title, mime, url in items:
            text = RULE if mime == "text/markdown" else f"<html><body><h1>{title}</h1><p>{RULE}</p></body></html>"
            item: dict[str, Any] = {
                "name": title,
                "title": title,
                "text": text,
                "mime": mime,
                **({"url": url} if url else {}),
            }
            put = data(await client.post(f"/v1/sources/{src['id']}/items", json=item))
            assert put["item"]["status"] == "indexed", put
    return kb


async def test_documents_filter_by_collection_and_type_and_facet_the_whole_base(client: httpx.AsyncClient) -> None:
    kb = await library(client)
    page = data(
        await client.get(
            f"/v1/knowledge-bases/{kb}/documents", params={"collection": "Cards", "docType": "web", "pageSize": 1}
        )
    )
    assert [(r["title"], r["docType"]) for r in page["data"]] == [("Lost card", "web")], page["data"]
    # A chip counts over the base with the other filters applied, not over the page shown: Type counts both Cards
    # documents, Collection counts every collection's web pages.
    assert page["facets"]["docType"] == {"text": 1, "web": 1}, page["facets"]
    assert page["facets"]["collection"] == {"Cards": 1}, page["facets"]
    every = data(await client.get(f"/v1/knowledge-bases/{kb}/documents", params={"pageSize": 1}))
    assert every["facets"]["collection"] == {"Cards": 2, "Compliance": 1}, every["facets"]
    assert every["pagination"]["total"] == 3, every["pagination"]


async def test_a_test_question_narrowed_to_a_collection_cites_only_it(client: httpx.AsyncClient) -> None:
    kb = await library(client)
    found = data(
        await client.post(
            f"/v1/knowledge-bases/{kb}/query",
            json={"question": "card dispute statement days", "collection": "Compliance"},
        )
    )
    assert {c["documentTitle"] for c in found["chunks"]} == {"Complaints policy"}, found["chunks"]
