"""A base's search filters, by failure mode: a piece outside the base's scope returned by the meaning lane (which
reads vectors, not the keyword query); an excluded tag losing to an included one; untagged documents kept when the
base says not to; and one base's filter applied to another base searched beside it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.files import KnowledgeFiles
from ops_kb.store.vectors import PgVectorStore

from .conftest import kb_client
from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .vectors_fake import ConceptEmbedder

REPAY = "You can repay all or part of your loan at any time; an early repayment charge may apply."
# Shares one word with REPAY: below the keyword lane's floor, near it in meaning.
PARAPHRASE = "what does it cost to clear my loan sooner"


@pytest.fixture
async def client(engine: AsyncEngine, tenant: str, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    if not await PgVectorStore(engine).ready():
        pytest.skip("This PostgreSQL has no pgvector; make db-move-image moves the local stack onto it.")
    files = KnowledgeFiles(tmp_path)
    async with kb_client(engine, tenant, files=files, readings=LocalReadings(files), embedder=ConceptEmbedder()) as c:
        yield c


async def base(client: httpx.AsyncClient, name: str, retrieval: dict[str, Any]) -> str:
    body = {"name": name, "owner": "james@harborpine.example", "retrieval": retrieval}
    return str(data(await client.post("/v1/knowledge-bases", json=body), 201)["id"])


async def pushed(client: httpx.AsyncClient, kb_ids: list[str], title: str, text: str, **source: Any) -> None:
    body = {"type": "push", "name": f"{title} feed", "kbIds": kb_ids, **source}
    src = data(await client.post("/v1/sources", json=body), 201)
    put = data(await client.post(f"/v1/sources/{src['id']}/items", json={"name": title, "title": title, "text": text}))
    assert put["item"]["status"] == "indexed", put


async def titles(client: httpx.AsyncClient, kb_ids: list[str], question: str, **extra: Any) -> set[str]:
    body = {"kbIds": kb_ids, "question": question, **extra}
    found = data(await client.post("/v1/knowledge-bases/search", json=body))
    return {p["title"] for p in found["passages"]}


async def test_a_piece_outside_the_scope_never_returns_from_the_meaning_lane(client: httpx.AsyncClient) -> None:
    kb = await base(client, "Lending help", {"searchMode": "meaning", "scopeCollections": ["Lending"]})
    await pushed(client, [kb], "Loan repayment", REPAY, collection="Lending")
    await pushed(client, [kb], "Card repayment", REPAY, collection="Cards")
    body = {"kbIds": [kb], "question": PARAPHRASE}
    found = data(await client.post("/v1/knowledge-bases/search", json=body))
    assert found["lanes"]["ran"] == ["meaning"], found["lanes"]
    assert {p["title"] for p in found["passages"]} == {"Loan repayment"}, found["passages"]


async def test_an_excluded_tag_wins_over_an_included_one(client: httpx.AsyncClient) -> None:
    kb = await base(client, "Fees", {"searchMode": "keyword", "tagsInclude": ["fees"], "tagsExclude": ["draft"]})
    await pushed(client, [kb], "Published fees", REPAY, tags=["fees"])
    await pushed(client, [kb], "Draft fees", REPAY, tags=["fees", "draft"])
    assert await titles(client, [kb], "early repayment charge loan") == {"Published fees"}


async def test_untagged_off_drops_untagged_pieces(client: httpx.AsyncClient) -> None:
    kb = await base(client, "Tagged only", {"searchMode": "keyword", "includeUntagged": False})
    await pushed(client, [kb], "Tagged", REPAY, tags=["lending"])
    await pushed(client, [kb], "Untagged", REPAY)
    assert await titles(client, [kb], "early repayment charge loan") == {"Tagged"}


async def test_several_bases_keep_each_bases_own_filter(client: httpx.AsyncClient) -> None:
    cards = await base(
        client,
        "Cards",
        {
            "searchMode": "keyword",
            "filters": {"match": "all", "conditions": [{"key": "product", "op": "is", "value": "cards"}]},
        },
    )
    wide = await base(client, "Everything", {"searchMode": "keyword"})
    card = [{"key": "product", "from": "static:cards"}]
    loan = [{"key": "product", "from": "static:loans"}]
    await pushed(client, [cards, wide], "Card charges", REPAY, collection="Cards", metadataMapping=card)
    await pushed(client, [cards, wide], "Loan charges", REPAY, collection="Lending", metadataMapping=loan)
    question = "early repayment charge loan"
    assert await titles(client, [cards], question) == {"Card charges"}
    assert await titles(client, [cards, wide], question) == {"Card charges", "Loan charges"}
    # The Test sheet's collection narrows every base searched, on top of each base's own filter.
    assert await titles(client, [cards, wide], question, collection="Lending") == {"Loan charges"}
