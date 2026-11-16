"""kb-service reading source files from files-service, against a fake of files-service's public file
routes (tests/files_fake.py): files from kb-service's own store move across on start, and a refusal from files-service
says what failed. Adding files by id: test_add_existing_files.py."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.__main__ import move_to_files_service
from ops_kb.agents import StaticAgents
from ops_kb.files import FilesServiceIntake, KnowledgeFiles
from ops_kb.search import HybridRetriever
from ops_kb.service import KnowledgeService
from ops_kb.store import KnowledgeStore

from .conftest import kb_client
from .files_fake import FakeFilesService
from .pdfs import RATES
from .readings_fake import LocalReadings
from .test_add_existing_files import stored
from .test_bases_and_sources import data
from .test_sync import file_source, upload


async def test_a_start_moves_files_from_kb_services_own_store_into_files_service(
    engine: AsyncEngine, tmp_path: Path, tenant: str
) -> None:
    """The shared stack switched kb-service to files-service while its sources held ids from kb-service's
    own store, so every sync after the switch failed them as missing. A start copies them across and the next sync
    finds each document unchanged."""
    old = KnowledgeFiles(tmp_path / "kb-files")
    async with kb_client(engine, tenant, files=old) as before:
        src = await file_source(before)
        await upload(before, src["id"], "rates.pdf", RATES)
        data(await before.post(f"/v1/sources/{src['id']}/sync"))
    fake = FakeFilesService()
    files = fake.client()
    intake = FilesServiceIntake(files)
    service = KnowledgeService(
        KnowledgeStore(engine),
        intake,
        HybridRetriever(engine),
        StaticAgents(),
        readings=LocalReadings(intake),
    )
    await move_to_files_service(service, old, [tenant])
    async with kb_client(engine, tenant, files=intake) as after:
        moved = data(await after.get(f"/v1/sources/{src['id']}"))
        # This files-service scans through the hook; the stack's has scanning off.
        await fake.client(service="scanner", scopes=["files:decide"]).report_scan(
            tenant, moved["config"]["fileIds"][0], status="clean", engine="clamav"
        )
        run = data(await after.post(f"/v1/sources/{src['id']}/sync"))
    assert (run["counts"]["unchanged"], run["counts"]["failed"]) == (1, 0), run
    assert (await files.get(tenant, "team_ops", moved["config"]["fileIds"][0])).name == "rates.pdf", moved


async def test_a_refusal_from_files_service_says_what_failed_not_a_generic_error(
    engine: AsyncEngine, tenant: str
) -> None:
    """Owner report (src_25d08fca0e83): files-service refused kb-service's token (401) on every read, and Activate
    and sync answered "Something went wrong on the server". The person is told the file store refused and what to do."""
    fake = FakeFilesService()
    files = fake.client()
    async with kb_client(engine, tenant, files=FilesServiceIntake(files)) as client:
        src = await file_source(client)
        fid = await stored(fake, files, tenant, "rates.pdf", RATES)
        data(await client.post(f"/v1/sources/{src['id']}/files", json={"fileIds": [fid]}))
        fake.refuse = 401
        r = await client.post(f"/v1/sources/{src['id']}/sync")
        assert r.status_code == 503, r.text
        body = r.json()["error"]
        assert body["code"] == "files_unavailable" and "refused" in body["message"] and "try again" in body["message"]
        refused = await client.post(f"/v1/sources/{src['id']}/files", json={"fileIds": [fid]})
        assert refused.status_code == 503 and refused.json()["error"]["code"] == "files_unavailable", refused.text


async def test_an_item_written_before_its_scan_is_refused_as_not_ready_then_read(
    engine: AsyncEngine, tenant: str
) -> None:
    """Writing an item or a page goes through files-service, which holds a new file unreadable until its scan says
    clean; the route answered 500 then. It answers 409 file_not_ready, and the same write after the scan is created."""
    fake = FakeFilesService()
    scanner = fake.client(service="scanner", scopes=["files:decide"])

    async def scanned() -> None:
        for fid, f in fake.files.items():
            if f["scan"]["status"] == "pending":
                await scanner.report_scan(tenant, fid, status="clean", engine="clamav")

    async with kb_client(engine, tenant, files=FilesServiceIntake(fake.client())) as client:
        kb = data(
            await client.post("/v1/knowledge-bases", json={"name": "Disputes", "owner": "james@harborpine.example"}),
            201,
        )
        src = data(await client.post("/v1/sources", json={"type": "push", "name": "Rules", "kbIds": [kb["id"]]}), 201)
        item = {"name": "chargeback-window", "title": "Chargeback window", "text": "Raised within 120 days."}
        early = await client.post(f"/v1/sources/{src['id']}/items", json=item)
        assert (early.status_code, early.json()["error"]["code"]) == (409, "file_not_ready"), early.text
        await scanned()
        put = data(await client.post(f"/v1/sources/{src['id']}/items", json=item))
        assert (put["outcome"], put["item"]["path"], put["item"]["status"]) == (
            "created",
            "chargeback-window.md",
            "indexed",
        )
        page = {"title": "Vault", "text": "Open at 8."}
        early = await client.post(f"/v1/knowledge-bases/{kb['id']}/pages", json=page)
        assert (early.status_code, early.json()["error"]["code"]) == (409, "file_not_ready"), early.text
        await scanned()
        assert data(await client.post(f"/v1/knowledge-bases/{kb['id']}/pages", json=page), 201)["title"] == "Vault"
