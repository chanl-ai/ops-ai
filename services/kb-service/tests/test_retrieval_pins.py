"""Search and retrieval results for one seeded corpus, pinned by which pieces come back and in what order, by failure
mode: a rewrite of the keyword or meaning lane's store (fulltext.py, vectors.py) changing which passages a question
finds, their order or their scores. Two bases, both lanes, a collection-scoped search, a question under both floors,
and the lanes' own store calls. On PostgreSQL with pgvector, as CI runs it. `KB_REPIN=1` rewrites the fixture."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.files import KnowledgeFiles
from ops_kb.store.fulltext import KeywordLane
from ops_kb.store.vectors import PgVectorStore
from ops_store import isolation

from .conftest import kb_client
from .pdfs import HARDSHIP, RATES, policy_pdf
from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_meaning_search import PARAPHRASE, Stack
from .test_reply_pins import compare, scrubbed
from .test_sync import upload
from .vectors_fake import ConceptEmbedder

PINS = Path(__file__).parent / "fixtures" / "retrieval-pins.json"
QUESTIONS = {
    "keyword": "five-year fixed mortgage rate",
    "eligibility": "How many mortgage payments can a borrower who lost their job defer?",
    "paraphrase": PARAPHRASE,
    "mixed": "late claim fee repayment loan mortgage",
    "nothing": "weather forecast tomorrow in Lisbon",
}
NOTES = policy_pdf("Branch notes", [("Opening hours", "Branches open at nine and close at five on weekdays.")])


@pytest.fixture
async def stack(engine: AsyncEngine, tenant: str, tmp_path: Path) -> AsyncIterator[Stack]:
    """kb-service with the concept embedder, so both lanes run; a database with no pgvector fails the pin."""
    with isolation.tenant_wide("test: whether the database has pgvector", tenant_id=tenant):
        has_vectors = await PgVectorStore(engine).ready()
    if not has_vectors:
        pytest.fail("The test database has no kb_unit_vectors, so the meaning lane cannot be pinned.")
    embedder, files = ConceptEmbedder(), KnowledgeFiles(tmp_path)
    readings = LocalReadings(files)
    async with kb_client(engine, tenant, files=files, readings=readings, embedder=embedder) as client:
        yield Stack(client, embedder, readings)


def named(value: Any, names: dict[str, str]) -> Any:
    """`value` with each base's and document's id replaced by its name and each score rounded, so the pin reads which
    pieces came back while the ids, new each run, are left out."""
    if isinstance(value, dict):
        return {k: named(v, names) for k, v in cast(dict[str, Any], value).items()}
    if isinstance(value, list):
        return [named(v, names) for v in cast(list[Any], value)]
    if isinstance(value, float):
        return round(value, 6)
    return names.get(value, value) if isinstance(value, str) else value


def passages(found: dict[str, Any], names: dict[str, str]) -> list[dict[str, Any]]:
    """Each passage as its base's and document's names, place and scores, in the order returned."""
    return [
        {
            "kb": names[p["kbId"]],
            "document": names[p["itemId"]],
            "section": p["section"],
            "page": p.get("page"),
            "version": p["version"],
            "score": round(p["score"], 6),
            "lanes": {k: round(v, 6) for k, v in sorted(p["lanes"].items())},
        }
        for p in found["passages"]
    ]


async def test_search_and_retrieval_return_the_same_pieces_in_the_same_order(
    stack: Stack, engine: AsyncEngine, tenant: str
) -> None:
    client = stack.client
    help_src, help_kb = await stack.base()
    body = {"type": "file", "name": "Lending PDFs", "collection": "Lending", "owner": "james@harborpine.example"}
    lending_src = data(await client.post("/v1/sources", json=body), 201)
    notes_body = {**body, "name": "Notes", "collection": "Branches"}
    notes_src = data(await client.post("/v1/sources", json=notes_body), 201)
    kb_body = {
        "name": "Lending",
        "owner": "james@harborpine.example",
        "sourceIds": [lending_src["id"], notes_src["id"]],
    }
    lending_kb = data(await client.post("/v1/knowledge-bases", json=kb_body), 201)
    await upload(client, lending_src["id"], "hardship.pdf", HARDSHIP)
    await upload(client, lending_src["id"], "rates.pdf", RATES)
    await upload(client, notes_src["id"], "notes.pdf", NOTES)
    for src in (lending_src, notes_src):
        assert data(await client.post(f"/v1/sources/{src['id']}/sync"))["status"] == "success"
    names = {help_kb["id"]: "Help", lending_kb["id"]: "Lending"}
    for src in (help_src, lending_src, notes_src):
        for item in data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]:
            names[item["id"]] = item["title"]
    both = [lending_kb["id"], help_kb["id"]]
    seen: dict[str, Any] = {}
    for label, question in QUESTIONS.items():
        found = await stack.search(both[0], question)
        seen[f"one:{label}"] = passages(found, names)
        found = data(await client.post("/v1/knowledge-bases/search", json={"kbIds": both, "question": question}))
        seen[f"both:{label}"] = {"passages": passages(found, names), "lanes": found["lanes"]}
    scoped = {"kbIds": both, "question": "when do branches open on weekdays", "collection": "Branches"}
    seen["collection"] = passages(data(await client.post("/v1/knowledge-bases/search", json=scoped)), names)
    query = {"question": QUESTIONS["eligibility"]}
    answered = data(await client.post(f"/v1/knowledge-bases/{lending_kb['id']}/query", json=query))
    seen["query"] = named(answered, names)
    # The lanes' own store calls, below the fusion: the rows each returns, in order.
    lane, vectors = KeywordLane(engine), PgVectorStore(engine)
    with isolation.tenant_wide("test: the seeded corpus's lanes", tenant_id=tenant):
        for label in ("keyword", "mixed"):
            hits = await lane.hits(tenant, both, QUESTIONS[label], threshold=0.3, limit=4)
            seen[f"hits:{label}"] = [
                {k: round(v, 6) if isinstance(v, float) else v for k, v in sorted(h.items())} for h in hits
            ]
        vector, _ = await stack.embedder.embed([PARAPHRASE], tenant=tenant)
        model, width = stack.embedder.model, stack.embedder.width
        near = await vectors.nearest(tenant, both, vector[0], model=model, width=width, limit=4)
        seen["nearest"] = [{k: round(v, 6) if isinstance(v, float) else v for k, v in sorted(n.items())} for n in near]
        seen["coverage"] = list(await vectors.coverage(tenant, both, model=model, width=width))
        seen["pendingCount"] = await vectors.pending_count(tenant, model=model, width=width)
        seen["pendingOtherModel"] = [
            sorted(p) for p in await vectors.pending(tenant, model="other-embed", width=width, limit=3)
        ]
    if not seen["both:paraphrase"]["passages"]:
        pytest.fail("the meaning lane found nothing, so the pin would not cover vectors.py")
    compare(scrubbed(seen), PINS)
