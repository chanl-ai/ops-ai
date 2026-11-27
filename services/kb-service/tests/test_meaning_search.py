"""Search by meaning beside keywords, by failure mode: a question in other words than the page's is missed; a lane
that could not run is reported as run (or not reported at all); a down embedding model fails the sync or the search;
units left unembedded stay so; a change of embedding model keeps the old vectors in use or reads every file again;
the threshold lets a weak meaning match through; the bases' own limit and mode are ignored for a caller's; and a
source taken out of a base is still found by its vectors."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_kb.embedding import Backlog, ModelsEmbedder, embed_all
from ops_kb.files import KnowledgeFiles
from ops_kb.retrieval import Search
from ops_kb.schedule import WITHDRAWN_KEPT
from ops_kb.search import HybridRetriever
from ops_kb.store import KnowledgeStore
from ops_kb.store.vectors import PgVectorStore, VectorHit
from ops_service_kit.model_calls import ModelCalls
from ops_store import isolation
from ops_store.dialect import vector_index_ddl

from .conftest import kb_client
from .pdfs import policy_pdf
from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_sync import file_source, upload
from .vectors_fake import ConceptEmbedder, concept_vector

SECTIONS = [
    (
        "Reporting a claim late",
        "If you tell us about a claim after the notification window has closed, we can still accept it when you "
        "explain the delay.",
    ),
    ("Early repayment", "You can repay all or part of your loan at any time; an early repayment charge may apply."),
    ("Late fees", "A late fee of four percent applies when a payment is more than fifteen days past due."),
]
HELP = policy_pdf("Customer help", SECTIONS)
# Shares one word ("loan") with the early repayment section: below the keyword lane's threshold, near it in meaning.
PARAPHRASE = "what does it cost to clear my loan sooner"


class Stack:
    def __init__(self, client: httpx.AsyncClient, embedder: ConceptEmbedder, readings: LocalReadings) -> None:
        self.client, self.embedder, self.readings = client, embedder, readings
        self.made = 0

    async def base(self, retrieval: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        src = await file_source(self.client)
        self.made += 1
        owner = "james@harborpine.example"
        body: dict[str, Any] = {"name": f"Help {self.made}", "owner": owner, "sourceIds": [src["id"]]}
        kb = data(await self.client.post("/v1/knowledge-bases", json=body), 201)
        if retrieval:
            data(await self.client.patch(f"/v1/knowledge-bases/{kb['id']}", json={"retrieval": retrieval}))
        await upload(self.client, src["id"], "help.pdf", HELP)
        assert data(await self.client.post(f"/v1/sources/{src['id']}/sync"))["status"] == "success"
        return src, kb

    async def search(self, kb_id: str, question: str, **extra: Any) -> dict[str, Any]:
        body = {"kbIds": [kb_id], "question": question, **extra}
        return data(await self.client.post("/v1/knowledge-bases/search", json=body))


@pytest.fixture
async def stack(engine: AsyncEngine, tenant: str, tmp_path: Path) -> AsyncIterator[Stack]:
    with isolation.tenant_wide("test: whether the database has pgvector", tenant_id=tenant):
        has_vectors = await PgVectorStore(engine).ready()
    if not has_vectors:
        # CI runs pgvector, so there a missing vector table is a failure; a local server on the old image is skipped
        # with the way to move it.
        if os.environ.get("CI"):
            pytest.fail("The test database has no kb_unit_vectors: its PostgreSQL lacks pgvector.")
        pytest.skip("This PostgreSQL has no pgvector; make db-move-image moves the local stack onto it.")
    embedder, files = ConceptEmbedder(), KnowledgeFiles(tmp_path)
    readings = LocalReadings(files)
    async with kb_client(engine, tenant, files=files, readings=readings, embedder=embedder) as client:
        yield Stack(client, embedder, readings)


def sections(found: dict[str, Any]) -> list[str]:
    return [p["section"].split(" > ")[-1] for p in found["passages"]]


async def test_a_question_in_other_words_is_found_by_meaning_and_both_lanes_say_they_ran(stack: Stack) -> None:
    _, kb = await stack.base()
    found = await stack.search(kb["id"], PARAPHRASE)
    assert sections(found)[:1] == ["Early repayment"], found
    top = found["passages"][0]
    assert set(top["lanes"]) == {"meaning"} and top["lanes"]["meaning"] >= 0.5, top
    assert found["lanes"] == {"asked": ["keyword", "meaning"], "ran": ["keyword", "meaning"], "skipped": []}
    assert found["cost"]["embeddingTokens"] == len(PARAPHRASE.split())
    coverage = data(await stack.client.get(f"/v1/knowledge-bases/{kb['id']}"))["embedding"]
    assert coverage["model"] == "concept-embed" and coverage["embedded"] == coverage["units"] > 0, coverage
    keyword_only = await stack.search(kb["id"], PARAPHRASE, limit=8)
    assert keyword_only["passages"], "the request's limit caps; it does not change the lanes"
    both = await stack.search(kb["id"], "early repayment charge on my loan")
    assert both["passages"][0]["lanes"].keys() == {"keyword", "meaning"}, both["passages"][0]


async def test_a_down_model_neither_fails_the_sync_nor_the_search_and_the_beat_embeds_later(
    stack: Stack, engine: AsyncEngine, tenant: str
) -> None:
    stack.embedder.down = "provider_unavailable"
    _, kb = await stack.base()
    found = await stack.search(kb["id"], "early repayment charge on my loan")
    assert found["lanes"]["ran"] == ["keyword"] and sections(found)[:1] == ["Early repayment"], found
    assert found["lanes"]["skipped"] == [{"lane": "meaning", "reason": "no_vectors"}], found["lanes"]
    backlog = Backlog()
    store, vectors = KnowledgeStore(engine), PgVectorStore(engine)
    assert await embed_all(store, vectors, stack.embedder, backlog) == 0
    assert backlog.last_error == "provider_unavailable" and backlog.pending and backlog.pending > 0
    stack.embedder.down = None
    assert await embed_all(store, vectors, stack.embedder, backlog) > 0
    assert backlog.pending == 0
    stack.embedder.down = "provider_unavailable"
    down = await stack.search(kb["id"], "early repayment charge on my loan")
    assert down["lanes"]["skipped"] == [{"lane": "meaning", "reason": "embedding_unavailable: provider_unavailable"}]
    assert sections(down)[:1] == ["Early repayment"]
    with isolation.tenant_wide("test: coverage", tenant_id=tenant):
        assert (await vectors.coverage(tenant, [kb["id"]], model="concept-embed", width=64))[0] > 0


async def test_a_new_embedding_model_embeds_every_unit_again_and_reads_no_file_again(
    stack: Stack, engine: AsyncEngine, tenant: str
) -> None:
    _, kb = await stack.base()
    reads = len(stack.readings.reads)
    before = stack.embedder.texts
    stack.embedder.model = "concept-embed-2"
    stale = await stack.search(kb["id"], PARAPHRASE)
    assert stale["lanes"]["skipped"] == [{"lane": "meaning", "reason": "no_vectors"}], "old vectors are never used"
    assert await embed_all(KnowledgeStore(engine), PgVectorStore(engine), stack.embedder, Backlog()) > 0
    assert stack.embedder.texts > before and len(stack.readings.reads) == reads
    assert sections(await stack.search(kb["id"], PARAPHRASE))[:1] == ["Early repayment"]


async def test_the_bases_own_settings_decide_lanes_threshold_and_limit(stack: Stack) -> None:
    _, keyword = await stack.base({"searchMode": "keyword"})
    found = await stack.search(keyword["id"], PARAPHRASE)
    assert found["lanes"]["asked"] == ["keyword"] and found["passages"] == [], found
    _, strict = await stack.base({"meaningThreshold": 0.95})
    assert (await stack.search(strict["id"], "notifying insurers belatedly about claims"))["passages"]
    assert (await stack.search(strict["id"], PARAPHRASE))["passages"] == [], "0.90 is under a 0.95 threshold"
    _, one = await stack.base({"chunkLimit": 1})
    assert len((await stack.search(one["id"], "late claim fee repayment loan"))["passages"]) == 1
    assert (await stack.search(one["id"], "weather forecast tomorrow"))["passages"] == []


async def test_a_source_taken_out_of_the_base_is_not_found_by_its_vectors(stack: Stack) -> None:
    src, kb = await stack.base()
    data(await stack.client.delete(f"/v1/knowledge-bases/{kb['id']}/sources/{src['id']}"))
    found = await stack.search(kb["id"], PARAPHRASE)
    assert found["passages"] == [], found


async def test_a_changed_document_keeps_the_ids_and_vectors_of_its_unchanged_pieces(
    stack: Stack, engine: AsyncEngine, tenant: str
) -> None:
    """Every new version withdrew every piece and wrote new ones, so one changed sentence re-embedded the whole
    document."""
    src, _ = await stack.base()
    [item] = data(await stack.client.get(f"/v1/sources/{src['id']}/items"))["data"]
    store = KnowledgeStore(engine)

    async def pieces() -> dict[str, str]:
        with isolation.tenant_wide("test: the item's live pieces", tenant_id=tenant):
            return {c.id: c.text for c in await store.chunks(tenant, item["id"])}

    before = await pieces()
    embedded = stack.embedder.texts
    changed = [*SECTIONS[:2], ("Late fees", "A late fee of five percent applies when a payment is past due.")]
    await upload(stack.client, src["id"], "help.pdf", policy_pdf("Customer help", changed))
    data(await stack.client.post(f"/v1/sources/{src['id']}/sync"))
    after = await pieces()
    kept = set(before) & set(after)
    assert len(kept) == len(before) - 1 and len(after) == len(before), (before, after)
    assert stack.embedder.texts - embedded == 1, "only the changed piece is embedded again"
    with isolation.tenant_wide("test: withdrawn pieces past their retention", tenant_id=tenant):
        # The beat purges what was withdrawn before now - WITHDRAWN_KEPT; a day past the retention, this one goes.
        assert await store.purge_withdrawn(tenant, before=datetime.now(UTC) - WITHDRAWN_KEPT) == 0
        later = datetime.now(UTC) + timedelta(days=1)
        assert await store.purge_withdrawn(tenant, before=later) == 1


async def test_the_two_lanes_have_their_own_floors(stack: Stack) -> None:
    """One threshold for a share of terms and for a cosine similarity let a keyword setting starve the meaning lane:
    0.5 is a fair share of terms and too high a similarity for most embedding models."""
    _, kb = await stack.base({"threshold": 0.99, "meaningThreshold": 0.3})
    found = await stack.search(kb["id"], PARAPHRASE)
    assert sections(found)[:1] == ["Early repayment"] and found["passages"][0]["lanes"].keys() == {"meaning"}, found


async def test_a_small_base_beside_a_large_one_still_gets_its_nearest_piece(
    stack: Stack, engine: AsyncEngine, tenant: str, database_url: str
) -> None:
    """The HNSW scan stops after its first candidates, before the knowledge base filter: a small base beside a large
    one of the same tenant got nothing back, reported as a meaning lane that ran."""
    _, kb = await stack.base()
    # Pieces nearer the question than the small base's answer, so the index's first candidates are all the large one's.
    crowd = [(f"Note {n}", f"{PARAPHRASE}? Note {n}.") for n in range(80)]
    src = await file_source(stack.client)
    body = {"name": "Crowd", "owner": "james@harborpine.example", "sourceIds": [src["id"]]}
    data(await stack.client.post("/v1/knowledge-bases", json=body), 201)
    await upload(stack.client, src["id"], "crowd.pdf", policy_pdf("Crowd", crowd))
    assert data(await stack.client.post(f"/v1/sources/{src['id']}/sync"))["status"] == "success"
    # The HNSW index for the test model's width (the chain makes the environment's), and a planner made to use it with
    # few candidates, as it does on a large table.
    async with engine.begin() as c:
        await c.execute(sa.text(str(vector_index_ddl("postgresql", "kb_unit_vectors", "embedding", 64))))
    tight = create_async_engine(
        database_url, connect_args={"server_settings": {"enable_seqscan": "off", "hnsw.ef_search": "5"}}
    )
    try:
        near = PgVectorStore(tight)
        vector, _ = await stack.embedder.embed([PARAPHRASE], tenant=tenant)
        with isolation.tenant_wide("test: the small tenant's search", tenant_id=tenant):
            rows = await near.nearest(
                tenant, [kb["id"]], vector[0], model=stack.embedder.model, width=stack.embedder.width, limit=8
            )
    finally:
        await tight.dispose()
    assert rows and "repay all or part" in rows[0]["text"], rows


async def test_a_meaning_lane_with_no_candidate_says_so_instead_of_ran(engine: AsyncEngine, tenant: str) -> None:
    """The lane was reported as run whenever the base had vectors, even when the index answered nothing."""

    class EmptyIndex(PgVectorStore):
        async def ready(self) -> bool:
            return True

        async def coverage(self, *_: Any, **__: Any) -> tuple[int, int]:
            return 3, 3

        async def nearest(self, *_: Any, **__: Any) -> list[VectorHit]:
            return []

    retriever = HybridRetriever(engine, ConceptEmbedder())
    retriever.vectors = EmptyIndex(engine)
    found = await retriever.search(tenant, ["kb_x"], PARAPHRASE, Search(lanes=("meaning",)))
    assert (found.ran, found.skipped) == ([], {"meaning": "no_candidates"}), found


async def test_off_postgresql_the_keyword_lane_says_it_was_skipped(tmp_path: Path) -> None:
    other = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'kb.db'}")
    try:
        with isolation.scope("t_x", "team_x"):
            found = await HybridRetriever(other).search("t_x", ["kb_x"], "mortgage rates", Search(lanes=("keyword",)))
    finally:
        await other.dispose()
    assert found.ran == [] and found.skipped == {"keyword": "no_full_text"}


@pytest.fixture
def short_search_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_KB_SEARCH_WAIT_S", "0.5")


async def test_a_slow_embedding_model_skips_the_meaning_lane_at_the_search_wait(
    short_search_wait: None, stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The question's embedding is bound by the search's wait, not the models endpoint's 120 s: past it the meaning
    lane is skipped as when the model is down, and the keyword lane answers."""
    _, kb = await stack.base()
    embed = stack.embedder.embed

    async def slow(texts: list[str], *, tenant: str) -> tuple[list[list[float]], int]:
        await asyncio.sleep(60)
        return await embed(texts, tenant=tenant)

    monkeypatch.setattr(stack.embedder, "embed", slow)
    found = await asyncio.wait_for(stack.search(kb["id"], "early repayment charge on my loan"), 5)
    assert found["lanes"]["skipped"] == [{"lane": "meaning", "reason": "embedding_unavailable: timeout"}], found
    assert sections(found)[:1] == ["Early repayment"]


class Models:
    """models-service's embeddings route as kb-service calls it: the reply names the model serving the alias, and a
    down model answers 503. `calls` counts every request."""

    def __init__(self) -> None:
        self.model, self.down, self.calls = "scripted/concept-embed", False, 0
        # A tenant whose budget is spent: the first one to call, when `spent` is set.
        self.spent: str | None = None
        self.refused: list[str] = []

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        tenant = request.headers["x-tenant-id"]
        if self.spent == "first":
            self.spent = tenant
        if tenant == self.spent:
            self.refused.append(tenant)
            error = {"code": "tenant_budget_exhausted", "message": "this tenant's budget is spent"}
            return httpx.Response(429, json={"success": False, "error": error})
        if self.down:
            error = {"code": "provider_unavailable", "message": "the provider did not answer"}
            return httpx.Response(503, json={"success": False, "error": error})
        body = json.loads(request.content)
        texts = [body["input"]] if isinstance(body["input"], str) else body["input"]
        rows = [{"object": "embedding", "index": i, "embedding": concept_vector(t, 64)} for i, t in enumerate(texts)]
        usage = {"prompt_tokens": sum(len(t.split()) for t in texts)}
        return httpx.Response(200, json={"object": "list", "model": self.model, "data": rows, "usage": usage})


async def _with_vectors(engine: AsyncEngine, tenant: str) -> None:
    with isolation.tenant_wide("test: whether the database has pgvector", tenant_id=tenant):
        if not await PgVectorStore(engine).ready():
            pytest.skip("This PostgreSQL has no pgvector; make db-move-image moves the local stack onto it.")


async def test_a_new_version_of_the_embedding_alias_embeds_every_unit_again(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    """An admin points the environment's embedding alias at another model (Settings, Model aliases): the alias name is
    unchanged, so vectors are keyed by the model that served them; the first search after the move makes them stale."""
    await _with_vectors(engine, tenant)
    models = Models()
    async with httpx.AsyncClient(transport=httpx.MockTransport(models.answer), base_url="http://models") as http:
        embedder = ModelsEmbedder(ModelCalls(http, "kb-key"), "bank-embed", 64)
        files = KnowledgeFiles(tmp_path)
        readings = LocalReadings(files)
        async with kb_client(engine, tenant, files=files, readings=readings, embedder=embedder) as client:
            stack = Stack(client, embedder, readings)  # pyright: ignore[reportArgumentType]
            store, vectors = KnowledgeStore(engine), PgVectorStore(engine)
            _, kb = await stack.base()
            await embed_all(store, vectors, embedder, Backlog())
            assert sections(await stack.search(kb["id"], PARAPHRASE))[:1] == ["Early repayment"]
            models.model = "scripted/concept-embed-2"
            stale = await stack.search(kb["id"], PARAPHRASE)
            assert stale["lanes"]["skipped"] == [{"lane": "meaning", "reason": "no_vectors"}], stale["lanes"]
            reads = len(readings.reads)
            assert await embed_all(store, vectors, embedder, Backlog()) > 0
            assert len(readings.reads) == reads
            again = await stack.search(kb["id"], PARAPHRASE)
            assert again["lanes"]["ran"] == ["keyword", "meaning"] and sections(again)[:1] == ["Early repayment"]
            embedding = data(await client.get(f"/v1/knowledge-bases/{kb['id']}"))["embedding"]
            assert embedding["model"] == "scripted/concept-embed-2" and embedding["embedded"] == embedding["units"], (
                embedding
            )


async def test_a_down_model_gives_one_reason_and_one_call_per_search_however_long_the_process_has_run(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    """A process that has not yet heard from the model must answer as one that has: the same skip reason, one call
    per search (the question's), and a base's detail read with no call and the stored vectors' model."""
    await _with_vectors(engine, tenant)
    models = Models()
    async with httpx.AsyncClient(transport=httpx.MockTransport(models.answer), base_url="http://models") as http:
        warm = ModelsEmbedder(ModelCalls(http, "kb-key"), "bank-embed", 64)
        files = KnowledgeFiles(tmp_path)
        readings = LocalReadings(files)
        async with kb_client(engine, tenant, files=files, readings=readings, embedder=warm) as client:
            stack = Stack(client, warm, readings)  # pyright: ignore[reportArgumentType]
            _, kb = await stack.base()
            await embed_all(KnowledgeStore(engine), PgVectorStore(engine), warm, Backlog())
            models.down = True
            calls = models.calls
            found = await stack.search(kb["id"], PARAPHRASE)
            assert models.calls == calls + 1
            reason = found["lanes"]["skipped"]
        assert reason == [{"lane": "meaning", "reason": "embedding_unavailable: provider_unavailable"}], reason
        cold = ModelsEmbedder(ModelCalls(http, "kb-key"), "bank-embed", 64)
        async with kb_client(engine, tenant, files=files, readings=readings, embedder=cold) as client:
            stack = Stack(client, cold, readings)  # pyright: ignore[reportArgumentType]
            stack.made = 1
            for _ in range(2):
                calls = models.calls
                found = await stack.search(kb["id"], PARAPHRASE)
                assert (found["lanes"]["skipped"], models.calls) == (reason, calls + 1)
            calls = models.calls
            embedding = data(await client.get(f"/v1/knowledge-bases/{kb['id']}"))["embedding"]
            assert (embedding["model"], models.calls) == ("scripted/concept-embed", calls), embedding
            _, unembedded = await stack.base()
            calls = models.calls
            found = await stack.search(unembedded["id"], PARAPHRASE)
            assert (found["lanes"]["skipped"], models.calls) == ([{"lane": "meaning", "reason": "no_vectors"}], calls)


async def test_a_tenant_the_model_refuses_holds_no_other_tenant_back(engine: AsyncEngine, tmp_path: Path) -> None:
    """One tenant out of budget is refused by models-service; the beat still embeds every other tenant's units."""
    tenants = [f"t_{uuid4().hex[:10]}" for _ in range(2)]
    await _with_vectors(engine, tenants[0])
    bases: dict[str, str] = {}
    for t in tenants:
        files = KnowledgeFiles(tmp_path / t)
        async with kb_client(engine, t, files=files) as client:
            stack = Stack(client, ConceptEmbedder(), LocalReadings(files))
            bases[t] = (await stack.base())[1]["id"]
    models = Models()
    models.spent = "first"
    async with httpx.AsyncClient(transport=httpx.MockTransport(models.answer), base_url="http://models") as http:
        embedder = ModelsEmbedder(ModelCalls(http, "kb-key"), "bank-embed", 64)
        await embed_all(KnowledgeStore(engine), PgVectorStore(engine), embedder, Backlog())
    vectors = PgVectorStore(engine)
    for t in tenants:
        with isolation.tenant_wide("test: coverage", tenant_id=t):
            embedded, units = await vectors.coverage(t, [bases[t]], model="scripted/concept-embed", width=64)
        assert (embedded == units > 0) == (t != models.spent), (t, models.spent, embedded, units)
