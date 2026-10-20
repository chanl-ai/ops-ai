"""The routes the console's knowledge pages call (c-056 T015), by failure mode: a sync nobody can find afterwards, a
sync option silently ignored, a paused source still syncing, a reprocess that pretends to be a new version, someone
else editing, detaching or verifying what they do not own, and a refresh that does not refresh."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from .conftest import kb_client
from .pdfs import HARDSHIP, RATES, scanned_pdf
from .test_bases_and_sources import data
from .test_sync import file_source, upload


async def synced(client: httpx.AsyncClient) -> tuple[dict[str, Any], dict[str, Any]]:
    src = await file_source(client)
    body = {"name": "Lending", "owner": "james@northfieldbank.com", "sourceIds": [src["id"]]}
    kb = data(await client.post("/v1/knowledge-bases", json=body), 201)
    await upload(client, src["id"], "hardship.pdf", HARDSHIP)
    await upload(client, src["id"], "scan.pdf", scanned_pdf())
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    return src, kb


async def test_every_sync_is_a_run_that_can_be_listed_and_opened(
    engine: AsyncEngine, client: httpx.AsyncClient
) -> None:
    src, _ = await synced(client)
    runs = data(await client.get(f"/v1/sources/{src['id']}/runs"))["data"]
    assert [(r["trigger"], r["status"]) for r in runs] == [("manual", "partial")], runs
    opened = data(await client.get(f"/v1/sync-runs/{runs[0]['id']}"))
    assert opened["counts"]["upserted"] == 1 and opened["errors"][0]["itemTitle"] == "scan.pdf"
    assert data(await client.get(f"/v1/sources/{src['id']}"))["recentRuns"][0]["id"] == runs[0]["id"]
    async with kb_client(engine, "t_other") as other:
        assert (await other.get(f"/v1/sync-runs/{runs[0]['id']}")).status_code == 404


async def test_sync_options_are_honoured_and_unknown_ones_refused(client: httpx.AsyncClient) -> None:
    src, _ = await synced(client)
    unknown = await client.post(f"/v1/sources/{src['id']}/sync", json={"fullSync": True})
    assert unknown.status_code == 400 and unknown.json()["error"]["code"] == "validation_failed", unknown.text
    retried = data(await client.post(f"/v1/sources/{src['id']}/sync", json={"retry": True}))
    assert (retried["trigger"], retried["counts"]["failed"], retried["counts"]["unchanged"]) == ("retry", 1, 1)
    full = data(await client.post(f"/v1/sources/{src['id']}/sync", json={"full": True}))
    assert full["trigger"] == "full" and full["counts"]["upserted"] == 1, full
    items = {i["path"]: i for i in data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]}
    assert items["hardship.pdf"]["version"] == "v1", "a rebuild of the same content is not a new version"
    assert data(await client.get("/v1/knowledge-changes"))["data"] == [], "and leaves no change row"


async def test_a_paused_source_does_not_sync_until_resumed(client: httpx.AsyncClient) -> None:
    src, _ = await synced(client)
    assert data(await client.post(f"/v1/sources/{src['id']}/pause"))["status"] == "paused"
    refused = await client.post(f"/v1/sources/{src['id']}/sync")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "source_paused", refused.text
    assert data(await client.post(f"/v1/sources/{src['id']}/resume"))["status"] == "active"
    assert (await client.post(f"/v1/sources/{src['id']}/sync")).status_code == 200


async def test_a_teammate_edits_detaches_and_verifies(
    engine: AsyncEngine, tenant: str, client: httpx.AsyncClient
) -> None:
    """Knowledge is shared by the team: someone other than the owner refreshes, edits, detaches and verifies (owner
    decision, 2026-10-17); a viewer or reviewer may not (test_write_roles)."""
    src, kb = await synced(client)
    item = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"][0]
    async with kb_client(engine, tenant, "maya@northfieldbank.com") as maya:
        data(await maya.post(f"/v1/knowledge-bases/{kb['id']}/refresh"))
    renamed = data(
        await client.patch(f"/v1/sources/{src['id']}", json={"name": "Lending PDFs 2026", "tags": ["policy"]})
    )
    assert (renamed["name"], renamed["tags"]) == ("Lending PDFs 2026", ["policy"])
    verified = data(await client.post(f"/v1/items/{item['id']}/verify", json={"verified": True}))
    assert verified["verified"] is True
    moved = data(await client.put(f"/v1/items/{item['id']}/owner", json={"owner": "lee@northfieldbank.com"}))
    assert moved["owner"] == "lee@northfieldbank.com"
    detached = data(await client.delete(f"/v1/knowledge-bases/{kb['id']}/sources/{src['id']}"))
    assert detached["sources"] == []


async def test_refresh_syncs_the_sources_and_lookups_list_what_exists(client: httpx.AsyncClient) -> None:
    src, kb = await synced(client)
    await upload(client, src["id"], "rates.pdf", RATES)
    data(await client.post(f"/v1/knowledge-bases/{kb['id']}/refresh"))
    items = {i["path"] for i in data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]}
    assert "rates.pdf" in items, "refresh synced the source, so the new file is indexed"
    data(await client.post(f"/v1/knowledge-bases/{kb['id']}/retry-failed"))
    triggers = [r["trigger"] for r in data(await client.get(f"/v1/sources/{src['id']}/runs"))["data"]]
    assert triggers[:2] == ["retry", "manual"], triggers
    looked = data(await client.get("/v1/knowledge/lookups"))
    assert "james@northfieldbank.com" in looked["owners"] and "Lending" in looked["collections"], looked
