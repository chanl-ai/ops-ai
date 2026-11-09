"""Search by meaning beside keywords, by failure mode: a question in other words than the page's is missed; a lane
that could not run is reported as run (or not reported at all); a down embedding model fails the sync or the search;
units left unembedded stay so; a change of embedding model keeps the old vectors in use or reads every file again;
the threshold lets a weak meaning match through; the bases' own limit and mode are ignored for a caller's; and a
source taken out of a base is still found by its vectors."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.embedding import Backlog, embed_all
from ops_kb.files import KnowledgeFiles
from ops_kb.schedule import WITHDRAWN_KEPT
from ops_kb.store import KnowledgeStore
from ops_kb.store.vectors import PgVectorStore
from ops_store import isolation

from .conftest import kb_client
from .pdfs import policy_pdf
from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_sync import file_source, upload
from .vectors_fake import ConceptEmbedder

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
    if not await PgVectorStore(engine).ready():
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
    _, strict = await stack.base({"threshold": 0.95})
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
            return {str(c["id"]): str(c["text"]) for c in await store.chunks(tenant, item["id"])}

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
