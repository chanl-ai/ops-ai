"""FAQ drafts, by failure mode: a draft searchable before a person approves it, an approved pair that cites itself
instead of its passage, an edit or a rejection that still answers, drafts asked again for a section that did not
change, and an approved pair kept as it was after its passage changed."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.ai import AiClient
from ops_kb.files import KnowledgeFiles
from ops_kb.store.knowledge import kb_changes

from .conftest import kb_client
from .pdfs import policy_pdf
from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_likely_questions import finished
from .test_ownership import _signed_in  # pyright: ignore[reportPrivateUsage]
from .test_sync import file_source, upload

SECTIONS = [
    ("Recalls", "A recall is asked of the receiving bank. It can take ten business days to come back."),
    ("Cut-off", "Wires sent after four in the afternoon leave on the next business day."),
]


class Drafter:
    """Drafts one pair per section, quoting the section's first sentence, and counts the sections it was asked for."""

    def __init__(self, asked: list[str]) -> None:
        self.asked = asked
        self.calls = self.input_tokens = self.output_tokens = 0

    def complete(self, prompt: str, *, alias: str, max_tokens: int) -> str:
        self.calls += 1
        section = re.search(r"Section: (.*)", prompt)
        name = section.group(1).split(" > ")[-1] if section else "-"
        self.asked.append(name)
        text = prompt.split("Section text:\n", 1)[1].strip()
        first = re.split(r"(?<=\.)\s", text)[0]
        pair = {"question": f"glimmerword what about {name.lower()}?", "answer": first, "quote": first}
        return json.dumps({"pairs": [pair]})


class Ai:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def __call__(self, tenant: str, run_id: str, ceiling: float) -> AiClient:
        return Drafter(self.asked)


@pytest.fixture
def ai() -> Ai:
    return Ai()


@pytest.fixture
async def client(engine: AsyncEngine, tenant: str, tmp_path: Path, ai: Ai) -> AsyncIterator[httpx.AsyncClient]:
    files = KnowledgeFiles(tmp_path)
    async with kb_client(engine, tenant, files=files, readings=LocalReadings(files), ai_clients=ai) as c:
        yield c


async def drafted(client: httpx.AsyncClient) -> tuple[dict[str, Any], dict[str, Any]]:
    src = await file_source(client)
    data(await client.patch(f"/v1/sources/{src['id']}", json={"ingest": {"strategies": ["structure", "faq_pairs"]}}))
    body = {"name": "Wires", "owner": "james@harborpine.example", "sourceIds": [src["id"]]}
    kb = data(await client.post("/v1/knowledge-bases", json=body), 201)
    await upload(client, src["id"], "wires.pdf", policy_pdf("Wire handbook", SECTIONS))
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    approved = data(await client.post(f"/v1/sources/{src['id']}/ai-approval", json={"decision": "approve"}))
    await finished(client, approved["rebuild"]["id"])
    return src, kb


async def test_the_source_says_which_ai_steps_wait_for_approval(client: httpx.AsyncClient) -> None:
    """The source page worked out the waiting steps itself while the API said none waited."""
    src = await file_source(client)
    data(await client.patch(f"/v1/sources/{src['id']}", json={"ingest": {"strategies": ["structure", "faq_pairs"]}}))
    waiting = data(await client.get(f"/v1/sources/{src['id']}"))
    assert waiting["aiStepsWaiting"] == ["faq_pairs"] and waiting["kindLabel"] == "Files", waiting
    data(await client.post(f"/v1/sources/{src['id']}/ai-approval", json={"decision": "approve"}))
    assert data(await client.get(f"/v1/sources/{src['id']}"))["aiStepsWaiting"] == []


async def queue(client: httpx.AsyncClient, view: str = "open") -> list[dict[str, Any]]:
    return data(await client.get("/v1/knowledge-changes", params={"view": view}))["data"]


async def search(client: httpx.AsyncClient, kb_id: str, question: str) -> list[dict[str, Any]]:
    body = {"kbIds": [kb_id], "question": question}
    return data(await client.post("/v1/knowledge-bases/search", json=body))["passages"]


async def test_a_draft_answers_only_once_approved_and_cites_its_source_passage(client: httpx.AsyncClient) -> None:
    _, kb = await drafted(client)
    waiting = await queue(client)
    questions = sorted(d["faq"]["question"] for d in waiting)
    assert questions == ["glimmerword what about cut-off?", "glimmerword what about recalls?"], questions
    recall = next(d for d in waiting if "recalls" in d["faq"]["question"])
    assert recall["before"] == "A recall is asked of the receiving bank." and recall["canDecide"], recall
    assert not any(p["matched"] == "faq" for p in await search(client, kb["id"], "glimmerword recalls")), "unreviewed"
    edited = data(
        await client.patch(
            f"/v1/knowledge-changes/{recall['id']}",
            json={"question": "glimmerword how is a recall asked?", "answer": "Of the receiving bank."},
        )
    )
    assert edited["status"] == "pending" and edited["faq"]["question"] == "glimmerword how is a recall asked?"
    assert edited["faq"]["addsWords"] == [], "every word of the answer is the passage's"
    loose = {"question": "glimmerword how is a recall asked?", "answer": "Of the receiving bank, free of charge."}
    flagged = data(await client.patch(f"/v1/knowledge-changes/{recall['id']}", json=loose))
    assert flagged["faq"]["addsWords"] == ["free", "charge"], flagged["faq"]
    cutoff = next(d for d in waiting if "cut-off" in d["faq"]["question"])
    approve = {"ids": [recall["id"]], "decision": "approve"}
    decided = data(await client.post("/v1/knowledge-changes/decide", json=approve))
    assert decided[0]["status"] == "approved" and decided[0]["decidedBy"] == "james@harborpine.example"
    data(await client.post("/v1/knowledge-changes/decide", json={"ids": [cutoff["id"]], "decision": "reject"}))
    [top] = [p for p in await search(client, kb["id"], "glimmerword how is a recall asked") if p["matched"] == "faq"]
    assert top["section"].endswith("Recalls") and "receiving bank" in top["text"], top
    assert not [p for p in await search(client, kb["id"], "glimmerword cut-off") if p["matched"] == "faq"]
    again = await client.post("/v1/knowledge-changes/decide", json={"ids": [cutoff["id"]], "decision": "approve"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "draft_decided", again.text


async def test_a_changed_section_is_drafted_again_and_its_approved_pair_marked_for_a_second_look(
    client: httpx.AsyncClient, ai: Ai
) -> None:
    src, _ = await drafted(client)
    ids = [d["id"] for d in await queue(client)]
    data(await client.post("/v1/knowledge-changes/decide", json={"ids": ids, "decision": "approve"}))
    ai.asked.clear()
    changed = [SECTIONS[0], ("Cut-off", "Wires sent after five in the afternoon leave on the next business day.")]
    await upload(client, src["id"], "wires.pdf", policy_pdf("Wire handbook", changed))
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    assert ai.asked == ["Cut-off"], "the unchanged section is not drafted again"
    open_now = await queue(client)
    assert sorted((d["status"], d["faq"]["answer"]) for d in open_now) == [
        ("pending", "Wires sent after five in the afternoon leave on the next business day."),
        ("source_changed", "Wires sent after four in the afternoon leave on the next business day."),
    ], open_now


async def test_the_queue_filters_by_origin_on_the_server_and_offers_decisions_only_to_who_may_make_them(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    """A From filter applied in the browser filters one page only; a viewer offered Approve meets a 403."""
    await drafted(client)
    drafts = data(await client.get("/v1/knowledge-changes", params={"view": "open", "origin": "generated_faq"}))
    syncs = data(await client.get("/v1/knowledge-changes", params={"view": "open", "origin": "source_sync"}))
    assert len(drafts["data"]) == 2 and syncs["data"] == [], (drafts["pagination"], syncs["pagination"])
    assert drafts["facets"]["origin"].get("generated_faq") == 2, drafts["facets"]
    assert all(d["canDecide"] for d in drafts["data"]), "the builder who owns the source may decide"
    async with _signed_in(engine, tenant, "vera@harborpine.example", "team_ops", {"team_ops": "viewer"}) as vera:
        seen = data(await vera.get("/v1/knowledge-changes", params={"view": "open"}))["data"]
        refused = await vera.post("/v1/knowledge-changes/decide", json={"ids": [seen[0]["id"]], "decision": "approve"})
    assert seen and not any(d["canDecide"] for d in seen), seen
    assert refused.status_code == 403, refused.text


async def test_the_queue_pages_in_the_database_and_reads_sources_once_per_page(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    """A queue that reads every change, and every source and base again for each row, slows with its history."""
    await drafted(client)
    statements: list[str] = []

    def seen(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        # The queue's reads of changes and bases; a rebuild's tail and the embedding beat share the engine and read
        # sources and units.
        if statement.lstrip().startswith("SELECT") and re.search(r"\bkb_(changes|bases)\b", statement):
            statements.append(statement)

    async def listed() -> tuple[dict[str, Any], int]:
        statements.clear()
        event.listen(engine.sync_engine, "before_cursor_execute", seen)
        try:
            page = data(await client.get("/v1/knowledge-changes", params={"view": "open", "pageSize": 5}))
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", seen)
        return page, len(statements)

    few, few_statements = await listed()
    async with engine.begin() as c:
        [row] = (await c.execute(sa.select(kb_changes).where(kb_changes.c.tenant_id == tenant).limit(1))).mappings()
        older = [
            {**row, "id": f"chg_old_{n:02}", "changed_at": row["changed_at"] - timedelta(days=n + 1)} for n in range(40)
        ]
        await c.execute(sa.insert(kb_changes), older)
    many, many_statements = await listed()
    assert few["pagination"]["total"] == 2 and many["pagination"]["total"] == 42, many["pagination"]
    assert len(many["data"]) == 5 and many["viewCounts"]["open"] == 42, many["viewCounts"]
    assert {d["id"] for d in few["data"]} <= {d["id"] for d in many["data"]}, "the newest come first"
    assert many_statements == few_statements, (few_statements, many_statements)
