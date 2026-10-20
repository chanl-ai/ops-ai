"""Adding files already in Files to a source by id (c-159): the console uploads to files-service first, then adds the
file id here, so this is the one way a file reaches a base. Against the files-service fake (tests/files_fake.py)."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_files_client import FilesClient
from ops_kb.files import FilesServiceIntake

from .conftest import kb_client
from .files_fake import FakeFilesService
from .pdfs import HARDSHIP, RATES
from .test_bases_and_sources import POLICIES, data
from .test_sync import file_source


async def stored(fake: FakeFilesService, files: FilesClient, tenant: str, name: str, body: bytes, **kw: Any) -> str:
    """A file uploaded to files-service as `team` (team_ops unless given), scanned clean unless `clean=False`."""
    team, clean = kw.get("team", "team_ops"), kw.get("clean", True)
    f = await files.write(
        tenant, team, body, name=name, mime="application/pdf", purpose="knowledge_source", uploaded_by="x"
    )
    if clean:
        await fake.client(service="scanner", scopes=["files:decide"]).report_scan(
            tenant, f.file.id, status="clean", engine="clamav"
        )
    return f.file.id


async def add(client: httpx.AsyncClient, source_id: str, *ids: str) -> httpx.Response:
    return await client.post(f"/v1/sources/{source_id}/files", json={"fileIds": list(ids)})


async def test_a_clean_file_from_files_is_added_once_referenced_and_indexed(engine: AsyncEngine, tenant: str) -> None:
    fake = FakeFilesService()
    files = fake.client()
    async with kb_client(engine, tenant, files=FilesServiceIntake(files)) as client:
        src = await file_source(client)
        fid = await stored(fake, files, tenant, "rates.pdf", RATES)
        added = data(await add(client, src["id"], fid, fid))
        data(await add(client, src["id"], fid))
        row = data(await client.get(f"/v1/sources/{src['id']}"))
        assert added == [{"fileId": fid, "name": "rates.pdf"}] and row["config"]["fileIds"] == [fid], (added, row)
        # Files keeps a file a base reads: the reference blocks deleting it there.
        assert fake.files[fid]["referenceCount"] == 1, fake.files[fid]
        run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
        items = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]
        assert run["counts"]["upserted"] == 1 and [i["path"] for i in items] == ["rates.pdf"], (run, items)


async def test_another_teams_file_or_a_made_up_id_is_refused(engine: AsyncEngine, tenant: str) -> None:
    fake = FakeFilesService()
    files = fake.client()
    async with kb_client(engine, tenant, files=FilesServiceIntake(files)) as client:
        src = await file_source(client)
        theirs = await stored(fake, files, tenant, "rates.pdf", RATES, team="team_cards")
        for fid in (theirs, "fil_9999"):
            r = await add(client, src["id"], fid)
            assert (r.status_code, r.json()["error"]["code"]) == (404, "file_not_found"), r.text
        created = await client.post("/v1/sources", json={"type": "file", "name": "Theirs", "fileIds": [theirs]})
        assert (created.status_code, created.json()["error"]["code"]) == (404, "file_not_found"), created.text
        row = data(await client.get(f"/v1/sources/{src['id']}"))
        assert row["config"]["fileIds"] == [] and fake.files[theirs]["referenceCount"] == 0, row


async def test_a_file_not_scanned_clean_is_refused_with_the_reason(engine: AsyncEngine, tenant: str) -> None:
    fake = FakeFilesService()
    files = fake.client()
    async with kb_client(engine, tenant, files=FilesServiceIntake(files)) as client:
        src = await file_source(client)
        pending = await stored(fake, files, tenant, "hardship.pdf", HARDSHIP, clean=False)
        r = await add(client, src["id"], pending)
        assert (r.status_code, r.json()["error"]["code"]) == (409, "file_not_ready"), r.text
        assert data(await client.get(f"/v1/sources/{src['id']}"))["config"]["fileIds"] == []


async def test_both_add_routes_refuse_the_same_files(engine: AsyncEngine, tenant: str) -> None:
    """The base's one-click Add documents and the source route share one check, so neither takes another team's file
    or one not scanned clean, and a refused add leaves no documents source behind."""
    fake = FakeFilesService()
    files = fake.client()
    async with kb_client(engine, tenant, files=FilesServiceIntake(files)) as client:
        src = await file_source(client)
        kb = data(await client.post("/v1/knowledge-bases", json=POLICIES), 201)
        theirs = await stored(fake, files, tenant, "rates.pdf", RATES, team="team_cards")
        pending = await stored(fake, files, tenant, "hardship.pdf", HARDSHIP, clean=False)
        for fid, refused in ((theirs, (404, "file_not_found")), (pending, (409, "file_not_ready"))):
            by_source = await add(client, src["id"], fid)
            by_base = await client.post(f"/v1/knowledge-bases/{kb['id']}/documents", json={"fileIds": [fid]})
            for r in (by_source, by_base):
                assert (r.status_code, r.json()["error"]["code"]) == refused, r.text
        assert data(await client.get(f"/v1/knowledge-bases/{kb['id']}"))["sources"] == []


async def test_documents_added_to_a_base_land_in_its_one_documents_source_active_and_indexed(
    engine: AsyncEngine, tenant: str
) -> None:
    """The Sources tab's Add documents: one call makes or reuses the base's documents source, adds the files and
    syncs, so after a reload the source is active and counts its items (UX knowledge-3)."""
    fake = FakeFilesService()
    files = fake.client()
    async with kb_client(engine, tenant, files=FilesServiceIntake(files)) as client:
        kb = data(await client.post("/v1/knowledge-bases", json=POLICIES), 201)
        first = await stored(fake, files, tenant, "rates.pdf", RATES)
        second = await stored(fake, files, tenant, "hardship.pdf", HARDSHIP)
        one = data(await client.post(f"/v1/knowledge-bases/{kb['id']}/documents", json={"fileIds": [first]}))
        two = data(await client.post(f"/v1/knowledge-bases/{kb['id']}/documents", json={"fileIds": [second]}))
        assert one["sourceId"] == two["sourceId"] and two["run"]["counts"]["upserted"] == 1, (one, two)
        detail = data(await client.get(f"/v1/knowledge-bases/{kb['id']}"))
        src = data(await client.get(f"/v1/sources/{one['sourceId']}"))
        assert [s["sourceId"] for s in detail["sources"]] == [one["sourceId"]], detail["sources"]
        assert src["name"] == "Lending policies documents", src
        assert (src["status"], src["itemsIndexed"], detail["stats"]["documents"]) == ("active", 2, 2), (src, detail)


async def test_a_refused_batch_releases_the_references_it_took_for_the_files_before_it(
    engine: AsyncEngine, tenant: str
) -> None:
    """A batch refused on its second id leaves the first file deletable in Files, not held by a source that never
    added it (c-159)."""
    fake = FakeFilesService()
    files = fake.client()
    async with kb_client(engine, tenant, files=FilesServiceIntake(files)) as client:
        src = await file_source(client)
        kept = await stored(fake, files, tenant, "hardship.pdf", HARDSHIP)
        data(await add(client, src["id"], kept))
        ours = await stored(fake, files, tenant, "rates.pdf", RATES)
        theirs = await stored(fake, files, tenant, "other.pdf", RATES + b"\n% other", team="team_cards")
        r = await add(client, src["id"], kept, ours, theirs)
        row = data(await client.get(f"/v1/sources/{src['id']}"))
    assert r.status_code == 404 and row["config"]["fileIds"] == [kept], (r.text, row)
    assert fake.files[ours]["referenceCount"] == 0, "the refused batch released the file it took before the refusal"
    assert fake.files[kept]["referenceCount"] == 1, "a file the source already held keeps its reference"


async def test_add_documents_finds_the_bases_documents_source_by_id_after_a_rename(
    engine: AsyncEngine, tenant: str
) -> None:
    """Found by its display name, a renamed base got a second documents source on its next Add documents (c-159)."""
    fake = FakeFilesService()
    files = fake.client()
    async with kb_client(engine, tenant, files=FilesServiceIntake(files)) as client:
        kb = data(await client.post("/v1/knowledge-bases", json=POLICIES), 201)
        first = await stored(fake, files, tenant, "rates.pdf", RATES)
        second = await stored(fake, files, tenant, "hardship.pdf", HARDSHIP)
        one = data(await client.post(f"/v1/knowledge-bases/{kb['id']}/documents", json={"fileIds": [first]}))
        data(await client.patch(f"/v1/knowledge-bases/{kb['id']}", json={"name": "Lending rules"}))
        two = data(await client.post(f"/v1/knowledge-bases/{kb['id']}/documents", json={"fileIds": [second]}))
        detail = data(await client.get(f"/v1/knowledge-bases/{kb['id']}"))
    assert one["sourceId"] == two["sourceId"] and len(detail["sources"]) == 1, (one, two, detail["sources"])
