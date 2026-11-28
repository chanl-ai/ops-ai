"""kb-service reading source files from files-service, against a fake of files-service's public file
routes (tests/files_fake.py): files from kb-service's own store move across on start, and a refusal from files-service
says what failed. Adding files by id: test_add_existing_files.py."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from pydantic import HttpUrl
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.__main__ import move_to_files_service, wait_for_files
from ops_kb.agents import StaticAgents
from ops_kb.files import FilesServiceIntake, KnowledgeFiles
from ops_kb.search import HybridRetriever
from ops_kb.service import KnowledgeService
from ops_kb.store import KnowledgeStore
from ops_service_kit.settings import FilesEndpoint, Settings

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


async def test_an_item_written_before_its_scan_is_kept_and_held_in_files_once_a_sync_finds_it_clean(
    engine: AsyncEngine, tenant: str
) -> None:
    """Files refuses a reference on a file it has not scanned, so taking one before recording the file left the source
    without it. The source records the file at once (409, read on the next sync), the first sync after the scan holds
    it in Files, and a new version lets go of the file it replaced."""
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

        async def write(text: str) -> list[str]:
            early = await client.post(f"/v1/sources/{src['id']}/items", json={**item, "text": text})
            assert (early.status_code, early.json()["error"]["code"]) == (409, "file_not_ready"), early.text
            held = data(await client.get(f"/v1/sources/{src['id']}"))["config"]["fileIds"]
            await scanned()
            data(await client.post(f"/v1/sources/{src['id']}/sync"))
            return held

        first = await write("Raised within 120 days.")
        assert len(first) == 1, "the source keeps the file it was sent before the scan"
        assert fake.files[first[0]]["referenceCount"] == 1, "the sync after the scan holds it in Files"
        second = await write("Raised within 90 days.")
        listed = [i["path"] for i in data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]]
    assert listed == ["chargeback-window.md"], "one item per name, answering through the new version's scan"
    assert len(second) == 1 and second != first, second
    assert (fake.files[first[0]]["referenceCount"], fake.files[second[0]]["referenceCount"]) == (0, 1)


async def test_a_new_version_of_one_name_keeps_the_file_another_name_holds(engine: AsyncEngine, tenant: str) -> None:
    """Two names with the same content share one file in Files, and the name that indexed it keeps it; a new version
    of the other name must not let go of the file the first still reads."""
    fake = FakeFilesService()
    scanner = fake.client(service="scanner", scopes=["files:decide"])
    async with kb_client(engine, tenant, files=FilesServiceIntake(fake.client())) as client:
        kb = data(
            await client.post("/v1/knowledge-bases", json={"name": "Disputes", "owner": "james@harborpine.example"}),
            201,
        )
        src = data(await client.post("/v1/sources", json={"type": "push", "name": "Rules", "kbIds": [kb["id"]]}), 201)
        for name, text in (
            ("window", "Raised within 120 days."),
            ("deadline", "Raised within 120 days."),
            ("deadline", "Raised within 90 days."),
        ):
            await client.post(
                f"/v1/sources/{src['id']}/items", json={"name": name, "title": "Chargeback window", "text": text}
            )
            for fid, f in fake.files.items():
                if f["scan"]["status"] == "pending":
                    await scanner.report_scan(tenant, fid, status="clean", engine="clamav")
            data(await client.post(f"/v1/sources/{src['id']}/sync"))
        held = data(await client.get(f"/v1/sources/{src['id']}"))["config"]["fileIds"]
        paths = [i["path"] for i in data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]]
    shared = next(fid for fid in fake.files if fake.blobs[fid] and b"120" in fake.blobs[fid])
    assert shared in held and fake.files[shared]["referenceCount"] == 1, (held, fake.files)
    assert "window.md" in paths, paths


async def test_start_up_waits_for_files_service_about_its_setting_not_a_probe_timeout_per_try() -> None:
    """files-service accepting connections and never answering: each probe gives up after the probe timeout, so the
    start-up wait ends near `ready_wait_s` rather than after tries of the files endpoint's 30 s."""

    async def hold(_r: asyncio.StreamReader, _w: asyncio.StreamWriter) -> None:
        await asyncio.sleep(60)

    server = await asyncio.start_server(hold, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    settings = Settings(
        files=FilesEndpoint(url=HttpUrl(f"http://127.0.0.1:{port}")), ready_wait_s=0.6, ready_probe_s=0.2
    )
    started = time.monotonic()
    try:
        await asyncio.wait_for(wait_for_files(settings), 5)
    finally:
        server.close()
    assert time.monotonic() - started < 2
