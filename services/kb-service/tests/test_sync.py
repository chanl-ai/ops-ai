"""Uploading files to a source and syncing them (c-056 T003), by failure mode: an uploaded PDF never indexed, its
passages losing page or section, a PDF without a text layer failing the whole sync or vanishing without a reason,
the same file indexed twice, and a document page that cannot show what was indexed."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity.fastapi import DEV_TEAM

from .conftest import intakes, kb_client
from .pdfs import HARDSHIP, RATES, partly_scanned_pdf, policy_pdf, scanned_pdf
from .test_bases_and_sources import data

PDF = {"Content-Type": "application/pdf"}


async def file_source(client: httpx.AsyncClient) -> dict[str, Any]:
    body = {"type": "file", "name": "Lending PDFs", "collection": "Lending", "owner": "james@harborpine.example"}
    return data(await client.post("/v1/sources", json=body), 201)


async def upload(client: httpx.AsyncClient, source_id: str, name: str, body: bytes) -> dict[str, Any]:
    """The bytes stored in the client's Files (the dev team's), then added to the source by id, as the console does."""
    stored = await intakes[client].put("t", DEV_TEAM, body, name=name, mime="application/pdf", actor="james")
    added = data(await client.post(f"/v1/sources/{source_id}/files", json={"fileIds": [stored.file_id]}))
    return {**added[0], "deduplicated": stored.deduplicated}


async def test_a_synced_pdf_is_indexed_by_page_and_section(client: httpx.AsyncClient) -> None:
    src = await file_source(client)
    await upload(client, src["id"], "hardship.pdf", HARDSHIP)
    run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
    assert (run["status"], run["counts"]["upserted"]) == ("success", 1), run
    item = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"][0]
    assert (item["status"], item["pageCount"], item["version"]) == ("indexed", 2, "v1")
    detail = data(await client.get(f"/v1/items/{item['id']}"))
    locations = [c["location"] for c in detail["detail"]["chunks"]]
    assert any("p. 1" in loc and "Eligibility" in loc for loc in locations), locations
    assert any("p. 2" in loc and "Interest" in loc for loc in locations), locations
    assert "defer up to three mortgage payments" in detail["detail"]["content"]


async def test_a_pdf_without_text_fails_with_a_reason_and_the_rest_index(client: httpx.AsyncClient) -> None:
    src = await file_source(client)
    await upload(client, src["id"], "rates.pdf", RATES)
    await upload(client, src["id"], "scan.pdf", scanned_pdf())
    run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
    assert (run["status"], run["counts"]["upserted"], run["counts"]["failed"]) == ("partial", 1, 1), run
    items = {i["path"]: i for i in data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]}
    assert items["rates.pdf"]["status"] == "indexed"
    assert items["scan.pdf"]["status"] == "failed" and items["scan.pdf"]["error"].startswith("no_text_layer")
    assert run["errors"][0]["itemTitle"] == "scan.pdf"


async def test_a_source_counts_its_documents_from_what_indexed(client: httpx.AsyncClient) -> None:
    """The source's counts are its items' statuses (c-072 T005), not every uploaded file reported as pending."""
    src = await file_source(client)
    await upload(client, src["id"], "rates.pdf", RATES)
    await upload(client, src["id"], "scan.pdf", scanned_pdf())
    before = data(await client.get(f"/v1/sources/{src['id']}"))
    assert (before["itemsIndexed"], before["itemsFailed"], before["itemsPending"]) == (0, 0, 2), before
    await client.post(f"/v1/sources/{src['id']}/sync")
    after = data(await client.get(f"/v1/sources/{src['id']}"))
    assert (after["itemsIndexed"], after["itemsFailed"], after["itemsPending"]) == (1, 1, 0), after
    listed = next(r for r in data(await client.get("/v1/sources"))["data"] if r["id"] == src["id"])
    assert (listed["itemsIndexed"], listed["itemsFailed"]) == (1, 1)


async def test_the_same_file_is_indexed_once(client: httpx.AsyncClient) -> None:
    src = await file_source(client)
    first = await upload(client, src["id"], "rates.pdf", RATES)
    again = await upload(client, src["id"], "rates-copy.pdf", RATES)
    assert again["fileId"] == first["fileId"] and again["deduplicated"]
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    resynced = data(await client.post(f"/v1/sources/{src['id']}/sync"))
    assert resynced["counts"]["unchanged"] == 1 and resynced["counts"]["upserted"] == 0, resynced
    assert len(data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]) == 1


async def test_a_knowledge_bases_documents_list_its_sources_items(client: httpx.AsyncClient) -> None:
    src = await file_source(client)
    kb = data(
        await client.post(
            "/v1/knowledge-bases",
            json={"name": "Lending", "owner": "maya@harborpine.example", "sourceIds": [src["id"]]},
        ),
        201,
    )
    await upload(client, src["id"], "hardship.pdf", HARDSHIP)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    docs = data(await client.get(f"/v1/knowledge-bases/{kb['id']}/documents"))["data"]
    assert [(d["title"], d["sourceName"]) for d in docs] == [("Mortgage Hardship Policy", "Lending PDFs")]
    assert data(await client.get(f"/v1/knowledge-bases/{kb['id']}"))["health"] == "healthy"


async def test_a_changed_file_replaces_its_old_passages(client: httpx.AsyncClient) -> None:
    """Reviewer's probe (c-056 T003): a file uploaded again under its name with new content becomes v2, and only v2's
    text is served, on the item page and to a question."""
    src = await file_source(client)
    body = {"name": "Rates", "owner": "maya@harborpine.example", "sourceIds": [src["id"]]}
    kb = data(await client.post("/v1/knowledge-bases", json=body), 201)
    await upload(client, src["id"], "rates.pdf", RATES)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    changed = policy_pdf("Rate Sheet", [("1 Fixed rates", "The five-year fixed mortgage rate is now 5.19 percent.")])
    await upload(client, src["id"], "rates.pdf", changed)
    run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
    items = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]
    assert [i["version"] for i in items] == ["v2"], (run, items)
    detail = data(await client.get(f"/v1/items/{items[0]['id']}"))["detail"]
    assert "5.19" in detail["content"] and "4.89" not in detail["content"], detail["content"]
    assert [v["status"] for v in detail["versions"]] == ["current", "superseded"]
    asked = data(
        await client.post(f"/v1/knowledge-bases/{kb['id']}/query", json={"question": "five-year fixed mortgage rate"})
    )
    assert {c["version"] for c in asked["citations"]} == {"v2"}, asked["citations"]


async def test_a_replaced_document_leaves_a_change_row_with_who_and_which_versions(
    engine: AsyncEngine, client: httpx.AsyncClient
) -> None:
    """c-056 T006: the Changes page shows who replaced which document, from which version to which, and what the
    section said before and after; another tenant sees none of it."""
    src = await file_source(client)
    body = {"name": "Rates", "owner": "maya@harborpine.example", "sourceIds": [src["id"]]}
    kb = data(await client.post("/v1/knowledge-bases", json=body), 201)
    await upload(client, src["id"], "rates.pdf", RATES)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    assert data(await client.get("/v1/knowledge-changes"))["data"] == [], "a first upload is not a change"
    changed = policy_pdf("Rate Sheet", [("1 Fixed rates", "The five-year fixed mortgage rate is now 5.19 percent.")])
    await upload(client, src["id"], "rates.pdf", changed)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    listed = data(await client.get("/v1/knowledge-changes", params={"view": "resolved", "kbId": kb["id"]}))
    row = listed["data"][0]
    assert (row["fromVersion"], row["toVersion"], row["proposedBy"], row["origin"]) == (
        "v1",
        "v2",
        "james@harborpine.example",
        "source_sync",
    )
    assert "Fixed rates" in row["section"] and "4.89" in row["before"] and "5.19" in row["after"], row
    assert row["kbs"] == [{"id": kb["id"], "name": "Rates"}] and listed["viewCounts"]["resolved"] == 1
    assert data(await client.get(f"/v1/knowledge-changes/{row['id']}"))["id"] == row["id"]
    async with kb_client(engine, "t_other") as other:
        assert data(await other.get("/v1/knowledge-changes"))["data"] == []


async def test_a_reupload_replaces_the_file_so_later_syncs_leave_the_document_alone(client: httpx.AsyncClient) -> None:
    """c-072 review: a re-upload kept both files under one name, so every later sync re-indexed the document twice
    (v4, v6, v8) and the source showed one document pending forever."""
    src = await file_source(client)
    await upload(client, src["id"], "rates.pdf", RATES)
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    changed = policy_pdf("Rate Sheet", [("1 Fixed rates", "The five-year fixed mortgage rate is now 5.19 percent.")])
    await upload(client, src["id"], "rates.pdf", changed)
    runs = [data(await client.post(f"/v1/sources/{src['id']}/sync"))["counts"] for _ in range(3)]
    assert [(r["listed"], r["upserted"], r["unchanged"]) for r in runs] == [(1, 1, 0), (1, 0, 1), (1, 0, 1)], runs
    items = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]
    assert [i["version"] for i in items] == ["v2"], items
    changes = data(await client.get("/v1/knowledge-changes", params={"view": "resolved"}))["data"]
    assert len(changes) == 1, changes
    row = data(await client.get(f"/v1/sources/{src['id']}"))
    assert (row["itemsIndexed"], row["itemsPending"]) == (1, 0), row


async def test_a_partly_scanned_pdf_indexes_its_text_and_says_which_pages_it_could_not_read(
    client: httpx.AsyncClient,
) -> None:
    """c-072 review: a PDF with some scanned pages indexed the rest silently; the document now names the pages."""
    src = await file_source(client)
    await upload(client, src["id"], "overdraft.pdf", partly_scanned_pdf())
    run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
    items = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]
    assert run["counts"]["upserted"] == 1 and items[0]["status"] == "indexed", (run, items)
    assert items[0]["warning"].startswith("Page 2 has no text layer"), items[0]


async def test_a_bases_counts_and_health_come_from_its_documents(client: httpx.AsyncClient) -> None:
    """c-094 T005: the list and the overview counted every base as 0 documents and healthy; a failed document now
    counts as a failure and marks the base degraded, and each source says what it contributes."""
    src = await file_source(client)
    body = {"name": "Teller", "owner": "maya@harborpine.example", "sourceIds": [src["id"]]}
    kb = data(await client.post("/v1/knowledge-bases", json=body), 201)
    await upload(client, src["id"], "hardship.pdf", HARDSHIP)
    await upload(client, src["id"], "scan.pdf", scanned_pdf())
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    got = data(await client.get(f"/v1/knowledge-bases/{kb['id']}"))
    chunks = sum(i["chunkCount"] for i in data(await client.get(f"/v1/sources/{src['id']}/items"))["data"])
    assert (got["stats"]["documents"], got["stats"]["failures"], got["stats"]["chunks"]) == (1, 1, chunks), got["stats"]
    assert chunks > 0 and got["health"] == "degraded" and got["healthReasons"], got
    assert [s["itemsContributed"] for s in got["sources"]] == [1], got["sources"]
    listed = next(b for b in data(await client.get("/v1/knowledge-bases"))["data"] if b["id"] == kb["id"])
    assert listed["stats"]["documents"] == 1, listed["stats"]


async def test_a_draft_source_becomes_active_on_its_first_sync_that_indexes(engine: AsyncEngine, tenant: str) -> None:
    """knowledge-2: the page says a draft activates on its first sync, but a successful sync left it draft, so the
    banner stayed and a person could not tell the document was live. A sync that indexes nothing keeps it draft."""
    async with kb_client(engine, tenant) as client:
        body = {"type": "file", "name": "Draft fees", "collection": "Ops", "status": "draft"}
        empty = data(await client.post("/v1/sources", json=body), 201)
        data(await client.post(f"/v1/sources/{empty['id']}/sync"))
        assert data(await client.get(f"/v1/sources/{empty['id']}"))["status"] == "draft", "nothing indexed, still draft"
        src = data(await client.post("/v1/sources", json={**body, "name": "Draft fees 2"}), 201)
        await upload(client, src["id"], "rates.pdf", RATES)
        run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
        assert run["status"] == "success", run
        row = data(await client.get(f"/v1/sources/{src['id']}"))
        assert row["status"] == "active"
        assert row["lastRunDurationSec"] == run["durationSec"], "the Last sync tile says how long the run took"
