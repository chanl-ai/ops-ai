"""Rerank and query rewrite, by failure mode: a step that calls a model while off, a rerank whose scores do not decide
the order or the limit, a reranker that fails taking the search down with it, a rewritten question that is not the
one searched or not shown, the agents' search route skipping the steps the Playground runs, and a rewrite mode that is
not built being saved."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.files import KnowledgeFiles
from ops_kb.query_steps import QueryStepFailed

from .conftest import kb_client
from .test_bases_and_sources import data

PAGES = [
    ("Wire cutoff", "## Cutoff\n\nA domestic wire sent after 5 pm goes out the next business day."),
    ("Wire fees", "## Fees\n\nAn outgoing domestic wire costs 25 dollars."),
]


class FakeQuery:
    """A reranker and rewriter that answer as told and record what they were asked."""

    def __init__(self, scores: dict[str, float] | None = None, rewritten: str = "", fail: bool = False) -> None:
        self.by_word, self.rewritten, self.fail = scores or {}, rewritten, fail
        self.asked: list[tuple[str, Any]] = []

    async def rewrite(self, question: str, instruction: str, *, alias: str, tenant: str) -> str:
        self.asked.append(("rewrite", (question, instruction, alias)))
        if self.fail:
            raise QueryStepFailed("model_unavailable: provider_down")
        return self.rewritten

    async def scores(self, question: str, pieces: list[str], *, alias: str, tenant: str) -> list[float]:
        self.asked.append(("rerank", (question, len(pieces), alias)))
        if self.fail:
            raise QueryStepFailed("model_unavailable: provider_down")
        return [next((v for w, v in self.by_word.items() if w in p), 0.0) for p in pieces]


async def base_with_pages(client: httpx.AsyncClient, retrieval: dict[str, Any] | None = None) -> str:
    kb = data(
        await client.post("/v1/knowledge-bases", json={"name": "Payments", "owner": "james@harborpine.example"}), 201
    )
    for title, text in PAGES:
        data(await client.post(f"/v1/knowledge-bases/{kb['id']}/pages", json={"title": title, "text": text}), 201)
    if retrieval:
        data(await client.patch(f"/v1/knowledge-bases/{kb['id']}", json={"retrieval": retrieval}))
    return str(kb["id"])


async def search(client: httpx.AsyncClient, kb_id: str, question: str) -> dict[str, Any]:
    return data(await client.post("/v1/knowledge-bases/search", json={"kbIds": [kb_id], "question": question}))


async def test_both_steps_are_off_by_default_and_call_no_model(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    fake = FakeQuery({"25 dollars": 9})
    async with kb_client(engine, tenant, files=KnowledgeFiles(tmp_path), query_model=fake) as client:
        found = await search(client, await base_with_pages(client), "domestic wire")
    assert found["passages"] and "rerank" not in found and "rewrite" not in found, found
    assert fake.asked == []


async def test_rerank_scores_decide_the_order_and_the_limit_on_the_agents_route(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    fake = FakeQuery({"25 dollars": 9, "5 pm": 2})
    async with kb_client(engine, tenant, files=KnowledgeFiles(tmp_path), query_model=fake) as client:
        kb_id = await base_with_pages(client, {"rerank": True})
        both = await search(client, kb_id, "domestic wire")
        data(await client.patch(f"/v1/knowledge-bases/{kb_id}", json={"retrieval": {"chunkLimit": 1}}))
        one = await search(client, kb_id, "domestic wire")
    assert [p["reranked"] for p in both["passages"]] == [9, 2], both["passages"]
    assert both["rerank"]["ran"] and both["rerank"]["scored"] == 2 and both["rerank"]["model"] == "bank-standard"
    assert [p["title"] for p in one["passages"]] == ["Wire fees"], one["passages"]
    assert fake.asked[0] == ("rerank", ("domestic wire", 2, "bank-standard")), fake.asked


async def test_a_failing_reranker_leaves_the_fused_search_and_says_why(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    fake = FakeQuery(fail=True)
    async with kb_client(engine, tenant, files=KnowledgeFiles(tmp_path), query_model=fake) as client:
        found = await search(client, await base_with_pages(client, {"rerank": True}), "domestic wire")
    assert len(found["passages"]) == 2 and all("reranked" not in p for p in found["passages"]), found
    assert found["rerank"] == {"ran": False, "model": "bank-standard", "scored": 0,
                               "skipped": "model_unavailable: provider_down", "ms": found["rerank"]["ms"]}  # fmt: skip


async def test_the_rewritten_question_is_the_one_searched_and_both_are_shown(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    fake = FakeQuery(rewritten="domestic wire cutoff")
    retrieval = {
        "rewrite": "rewrite",
        "rewriteInstructions": "Use the bank's payment terms.",
        "queryModel": "bank-fast",
    }
    async with kb_client(engine, tenant, files=KnowledgeFiles(tmp_path), query_model=fake) as client:
        kb_id = await base_with_pages(client, retrieval)
        answer = data(
            await client.post(f"/v1/knowledge-bases/{kb_id}/query", json={"question": "how late can money leave"})
        )
    assert answer["rewrite"]["asked"] == "how late can money leave", answer["rewrite"]
    assert answer["rewrite"]["rewritten"] == "domestic wire cutoff", answer["rewrite"]
    assert answer["passages"] and answer["passages"][0]["title"] == "Wire cutoff", answer["passages"]
    assert fake.asked == [("rewrite", ("how late can money leave", "Use the bank's payment terms.", "bank-fast"))]


async def test_a_rewrite_mode_that_is_not_built_is_refused(client: httpx.AsyncClient) -> None:
    kb_id = await base_with_pages(client)
    refused = await client.patch(f"/v1/knowledge-bases/{kb_id}", json={"retrieval": {"rewrite": "expand"}})
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "invalid_retrieval", refused.text
