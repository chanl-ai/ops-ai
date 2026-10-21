"""The banker demo's knowledge seed (c-058 T001) against kb-service in process: the rendered PDFs index by page and
section, each base belongs to its owner, every covered demo question clears the retrieval floor and the uncovered
one gets no passage, and version 2 of the fee schedule replaces version 1."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity.fastapi import DEV_TEAM
from ops_kb.agents import StaticAgents
from ops_kb.files import KnowledgeFiles
from ops_kb.seed import seed_demo
from ops_kb.service import KnowledgeService, Who
from ops_kb.store import KnowledgeStore
from ops_kb.store.fulltext import PostgresFullTextRetriever

from .conftest import kb_client

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seed_demo_knowledge.py"


def seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_demo_knowledge", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rendering_is_byte_identical_across_runs() -> None:
    seed = seed_module()
    text = (seed.SEED / "fee-schedule-v1.md").read_text()
    assert seed.render(text, "Fee Schedule") == seed.render(text, "Fee Schedule")


def test_a_harness_gets_owner_headers_from_one_token_or_dev() -> None:
    seed = seed_module()
    assert seed.owner_headers(token="t")[seed.NADIA] == {"Authorization": "Bearer t"}
    # Dev headers name each base's team, so its files go into the Files of the team that owns the source.
    dev = seed.owner_headers(dev=True)
    assert dev[seed.NADIA] == {"X-Dev-User": seed.NADIA, "X-Team-Id": "team_security"}, dev
    with pytest.raises(ValueError, match="token or dev"):
        seed.owner_headers()


async def test_the_seed_indexes_both_bases_for_their_owners_and_clears_the_floor(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    seed = seed_module()
    pdfs = seed.render_all()
    assert {p.name for p in pdfs.values()} == {
        "retail-product-sheet.pdf",
        "branch-operations-manual.pdf",
        "fee-schedule-v1.pdf",
        "fee-schedule-v2.pdf",
    }
    files = KnowledgeFiles(tmp_path)
    async with (
        kb_client(engine, tenant, email=seed.JAMES, files=files) as james,
        kb_client(engine, tenant, email=seed.NADIA, files=files) as nadia,
    ):

        async def store(_kb: httpx.AsyncClient, name: str, body: bytes) -> str:
            return (await files.put(tenant, DEV_TEAM, body, name=name, mime="application/pdf", actor="seed")).file_id

        seeded = await seed.seed({seed.JAMES: james, seed.NADIA: nadia}, store, pdfs)
        retail = (await james.get(f"/v1/knowledge-bases/{seeded.retail_kb}")).json()["data"]
        branch = (await nadia.get(f"/v1/knowledge-bases/{seeded.branch_kb}")).json()["data"]
        assert (retail["owner"], branch["owner"]) == (seed.JAMES, seed.NADIA)
        assert retail["health"] == "healthy" and branch["health"] == "healthy"
        # Sections became pages: a fee answer cites the fee schedule's page and section.
        answers = await seed.ask({seed.JAMES: james, seed.NADIA: nadia}, seeded)
        assert all(a["ok"] for a in answers), answers
        # A question no base covers finds nothing; every covered one (the rate, minimum balance and fee too) is cited.
        assert [a["score"] is None for a in answers] == [not covered for _, _, covered in seed.QUESTIONS]
        wire = next(a for a in answers if "wire" in a["question"])
        assert wire["cites"] and wire["cites"].startswith("Fee Schedule p.")
        # A second run reuses the bases and sources: nothing new, and the sync says unchanged.
        again = await seed.seed({seed.JAMES: james, seed.NADIA: nadia}, store, pdfs)
        assert (again.retail_kb, again.branch_kb) == (seeded.retail_kb, seeded.branch_kb)
        listed = (await james.get("/v1/knowledge-bases", params={"pageSize": 50})).json()["data"]["data"]
        assert sorted(b["name"] for b in listed) == ["Branch operations", "Retail products"]
        # Version 2 replaces version 1 under the same file name, and the fee answer moves to it.
        run = await seed.replace_fee_schedule(nadia, store, seeded, pdfs["fee-schedule-v2"].read_bytes())
        assert run["status"] == "success" and run["counts"]["upserted"] == 1, run
        after = (
            await james.post(
                f"/v1/knowledge-bases/{seeded.branch_kb}/query", json={"question": "fee for an outgoing wire transfer"}
            )
        ).json()["data"]
        assert "35.00" in after["answer"] and "30.00" not in after["answer"], after["answer"]
        changes = (await nadia.get("/v1/knowledge-changes")).json()["data"]["data"]
        assert any("Fee Schedule changed from v1 to v2" in c["summary"] for c in changes), changes


async def test_each_question_is_asked_by_the_team_that_owns_its_base() -> None:
    """Under platform sign-in a person reads only their team's bases (c-407): asking every question as James, in the
    operations team, answered 404 on Security's Branch operations and stopped uc-248 and uc-249 in setup (c-453)."""
    seed = seed_module()
    asked: dict[str, set[str]] = {seed.JAMES: set(), seed.NADIA: set()}

    def owner_of(email: str) -> httpx.AsyncClient:
        def answer(request: httpx.Request) -> httpx.Response:
            asked[email].add(request.url.path.split("/")[3])
            return httpx.Response(200, json={"success": True, "data": {"chunks": [], "citations": []}})

        return httpx.AsyncClient(transport=httpx.MockTransport(answer), base_url="http://kb")

    seeded = seed.Seeded("kb_retail", "kb_branch", "src_retail", "src_manual", "src_fees")
    async with owner_of(seed.JAMES) as james, owner_of(seed.NADIA) as nadia:
        await seed.ask({seed.JAMES: james, seed.NADIA: nadia}, seeded)
    assert asked == {seed.JAMES: {"kb_retail"}, seed.NADIA: {"kb_branch"}}, asked


async def test_a_dev_start_seeds_both_bases_under_the_ids_the_agents_name(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    """The FAQ agents' seed names kb_retail_products and kb_branch_operations; the bases must exist under those ids,
    indexed, after a start, and a second start must change nothing (c-072 T006)."""
    store = KnowledgeStore(engine)
    service = KnowledgeService(store, KnowledgeFiles(tmp_path), PostgresFullTextRetriever(engine), StaticAgents())
    assert await seed_demo(service, tenant) == ["kb_retail_products", "kb_branch_operations"]
    assert await seed_demo(service, tenant) == [], "a second start adds nothing"
    await store.remove_base(tenant, "kb_retail_products", by="j.richardson@harborpine.example")
    assert await seed_demo(service, tenant) == [], "a demo base someone retired is not brought back"
    other = f"{tenant}_hand"
    await service.create_base(
        Who(other, "j.richardson@harborpine.example", "team_ops"),
        {"name": "Retail products", "owner": "j.richardson@harborpine.example"},
    )
    assert await seed_demo(service, other) == ["kb_branch_operations"], (
        "a base of the same name made by hand is left as it is"
    )
    agents_seed = json.loads((Path(__file__).parents[2] / "agents-service" / "seed" / "chat_agents.json").read_text())
    named = {a["id"]: a["default_kb_ids"] for a in agents_seed if a["id"] in ("ag_advisor", "ag_policy")}
    assert named == {"ag_advisor": ["kb_retail_products"], "ag_policy": ["kb_branch_operations"]}
    async with kb_client(engine, tenant, email="j.richardson@harborpine.example", files=KnowledgeFiles(tmp_path)) as c:
        answer = (
            # The base is team_security's; a person reads it acting in that team (c-407).
            await c.post(
                "/v1/knowledge-bases/kb_branch_operations/query",
                json={"question": "fee for an outgoing wire transfer"},
                headers={"X-Team-Id": "team_security"},
            )
        ).json()["data"]
    assert answer["citations"] and answer["citations"][0]["page"], answer


async def test_a_dev_start_leaves_a_persons_source_of_a_demo_sources_name_alone(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    """c-072 review: the seed reused any source of a demo source's name, uploading into it as the demo owner; a
    different owner raised Forbidden and stopped kb-service starting. The base is skipped and the source untouched."""
    store = KnowledgeStore(engine)
    service = KnowledgeService(store, KnowledgeFiles(tmp_path), PostgresFullTextRetriever(engine), StaticAgents())
    mine = await service.create_source(
        Who(tenant, "m.okafor@harborpine.example", "team_ops"),
        {"type": "file", "name": "Fee schedule", "collection": "Mine", "owner": "m.okafor@harborpine.example"},
    )
    assert await seed_demo(service, tenant) == ["kb_retail_products"]
    row = next(s for s in await store.sources(tenant) if s["id"] == mine["id"])
    assert row["file_ids"] == [] and row["owner"] == "m.okafor@harborpine.example", row


async def test_a_start_on_a_new_file_store_uploads_the_demo_files_again(
    engine: AsyncEngine, tenant: str, tmp_path: Path
) -> None:
    """c-094: the shared stack moved kb-service from its own store to files-service, so the demo sources held file
    ids the new store had never seen and every sync failed. The next start uploads the demo files again."""
    store = KnowledgeStore(engine)
    retriever = PostgresFullTextRetriever(engine)
    before = KnowledgeService(store, KnowledgeFiles(tmp_path / "before"), retriever, StaticAgents())
    assert await seed_demo(before, tenant) == ["kb_retail_products", "kb_branch_operations"]
    after = KnowledgeService(store, KnowledgeFiles(tmp_path / "after"), retriever, StaticAgents())
    assert await seed_demo(after, tenant) == ["kb_retail_products", "kb_branch_operations"]
    assert await seed_demo(after, tenant) == [], "a second start on the new store changes nothing"
    for s in await store.sources(tenant):
        assert len(s["file_ids"]) == 1, s
        await after.files.read(tenant, "team_ops" if "Retail" in s["name"] else "team_security", s["file_ids"][0])
