"""kb-service reading source files from files-service, against a fake of files-service's public file
routes (tests/files_fake.py): files from kb-service's own store move across on start, and a refusal from files-service
says what failed. Adding files by id: test_add_existing_files.py."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
import sqlalchemy as sa
from httpx import AsyncClient
from pydantic import HttpUrl
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.__main__ import move_to_files_service, wait_for_files
from ops_kb.agents import StaticAgents
from ops_kb.files import FilesServiceIntake, KnowledgeFiles
from ops_kb.search import HybridRetriever
from ops_kb.service import KnowledgeService
from ops_kb.store import KnowledgeStore
from ops_kb.store.knowledge import kb_sources
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

        waiting: dict[str, int] = {}

        async def write(text: str) -> list[str]:
            early = await client.post(f"/v1/sources/{src['id']}/items", json={**item, "text": text})
            assert (early.status_code, early.json()["error"]["code"]) == (409, "file_not_ready"), early.text
            held = data(await client.get(f"/v1/sources/{src['id']}"))["config"]["fileIds"][-1:]
            waiting.update({f: x["referenceCount"] for f, x in fake.files.items()})
            await scanned()
            data(await client.post(f"/v1/sources/{src['id']}/sync"))
            return held

        first = await write("Raised within 120 days.")
        assert len(first) == 1, "the source keeps the file it was sent before the scan"
        assert fake.files[first[0]]["referenceCount"] == 1, "the sync after the scan holds it in Files"
        second = await write("Raised within 90 days.")
        assert waiting[first[0]] == 1, "the earlier version stays held in Files while the new one is scanned"
        listed = [i["path"] for i in data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]]
    assert listed == ["chargeback-window.md"], "one item per name, answering through the new version's scan"
    assert len(second) == 1 and second != first, second
    assert (fake.files[first[0]]["referenceCount"], fake.files[second[0]]["referenceCount"]) == (0, 1)


async def test_a_new_version_of_one_name_keeps_the_file_another_name_holds(engine: AsyncEngine, tenant: str) -> None:
    """Two names with the same content share one file in Files, and the name that indexed it keeps it; a new version
    of the other name must not let go of the file the first still reads."""
    fake = FakeFilesService()
    async with kb_client(engine, tenant, files=FilesServiceIntake(fake.client())) as client:
        kb = data(
            await client.post("/v1/knowledge-bases", json={"name": "Disputes", "owner": "james@harborpine.example"}),
            201,
        )
        src = data(await client.post("/v1/sources", json={"type": "push", "name": "Rules", "kbIds": [kb["id"]]}), 201)
        said: list[tuple[str, int]] = []
        for name, text in (
            ("window", "Raised within 120 days."),
            ("deadline", "Raised within 60 days."),
            ("deadline", "Raised within 120 days."),
            ("deadline", "Raised within 90 days."),
        ):
            res = await client.post(
                f"/v1/sources/{src['id']}/items", json={"name": name, "title": "Chargeback window", "text": text}
            )
            said.append((name, res.status_code))
            await scan_all(fake, tenant)
            data(await client.post(f"/v1/sources/{src['id']}/sync"))
            if len(said) == 3:
                sixty = next(fid for fid in fake.files if b"60" in fake.blobs[fid])
                assert fake.files[sixty]["referenceCount"] == 1, "a refused write keeps the name's own file"
        assert said[2] == ("deadline", 400), said
        held = data(await client.get(f"/v1/sources/{src['id']}"))["config"]["fileIds"]
        paths = [i["path"] for i in data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]]
    shared = next(fid for fid in fake.files if fake.blobs[fid] and b"120" in fake.blobs[fid])
    assert shared in held and fake.files[shared]["referenceCount"] == 1, (held, fake.files)
    assert "window.md" in paths, paths


async def scan_all(fake: FakeFilesService, tenant: str, verdict: str = "clean") -> None:
    """Files' scanner deciding every file still pending, as the scan hook does."""
    scanner = fake.client(service="scanner", scopes=["files:decide"])
    for fid, f in list(fake.files.items()):
        if f["scan"]["status"] == "pending":
            await scanner.report_scan(tenant, fid, status=verdict, engine="clamav")  # pyright: ignore[reportArgumentType]


async def push_source(client: AsyncClient) -> str:
    kb = data(
        await client.post("/v1/knowledge-bases", json={"name": "Disputes", "owner": "james@harborpine.example"}), 201
    )
    return data(await client.post("/v1/sources", json={"type": "push", "name": "Rules", "kbIds": [kb["id"]]}), 201)[
        "id"
    ]


async def test_a_version_its_scan_refuses_marks_the_item_failed_and_a_resend_after_a_clear_scan_reads_it(
    engine: AsyncEngine, tenant: str
) -> None:
    """A refused scan was read as "not scanned yet" on every sync and a resend answered 409 forever. The item says
    the scan refused it, the sync counts it failed, and once Files clears the file a resend of it is read."""
    fake = FakeFilesService()
    async with kb_client(engine, tenant, files=FilesServiceIntake(fake.client())) as client:
        src = await push_source(client)
        item = {"name": "window", "title": "Chargeback window", "text": "Raised within 120 days."}
        await client.post(f"/v1/sources/{src}/items", json=item)
        await scan_all(fake, tenant, "infected")
        run = data(await client.post(f"/v1/sources/{src}/sync"))
        assert run["counts"]["failed"] == 1 and any("found it infected" in x for x in run["log"]), run
        again = data(await client.post(f"/v1/sources/{src}/items", json=item))["item"]
        assert again["status"] == "failed" and "scan" in str(again), again
        fid = next(iter(fake.files))
        cleaner = fake.client(service="scanner", scopes=["files:decide"])
        await cleaner.report_scan(tenant, fid, status="clean", engine="clamav")
        read = data(await client.post(f"/v1/sources/{src}/items", json=item))["item"]
    assert read["status"] == "indexed" and fake.files[fid]["referenceCount"] == 1, (read, fake.files)


async def test_removing_a_source_lets_go_of_every_file_it_held(engine: AsyncEngine, tenant: str) -> None:
    """A removed source released nothing, so Files kept its files undeletable for a source that is gone."""
    fake = FakeFilesService()
    async with kb_client(engine, tenant, files=FilesServiceIntake(fake.client())) as client:
        src = await push_source(client)
        for text in ("Raised within 120 days.", "Raised within 90 days."):
            await client.post(f"/v1/sources/{src}/items", json={"name": "window", "title": "W", "text": text})
            await scan_all(fake, tenant)
            data(await client.post(f"/v1/sources/{src}/sync"))
        assert sorted(f["referenceCount"] for f in fake.files.values()) == [0, 1], fake.files
        assert (await client.delete(f"/v1/sources/{src}")).status_code == 204
    assert all(f["referenceCount"] == 0 for f in fake.files.values()), fake.files


class _ScannedAtOnce(FakeFilesService):
    """A Files whose scan finishes as the upload does, so a write takes its reference straight away."""

    def handle(self, request: httpx.Request) -> httpx.Response:
        res = super().handle(request)
        for f in self.files.values():
            f["scan"] = {"status": "clean", "engine": "clamav"}
        return res


async def test_two_writes_of_one_name_at_once_leave_only_the_newest_file_held(engine: AsyncEngine, tenant: str) -> None:
    """A write took its reference after recording the file, so a concurrent write of the same name could release a
    file the first then held again, for good."""
    fake = _ScannedAtOnce()
    async with kb_client(engine, tenant, files=FilesServiceIntake(fake.client())) as client:
        src = await push_source(client)
        body = [{"name": "window", "title": "W", "text": f"Raised within {d} days."} for d in (120, 90, 60)]
        await asyncio.gather(*(client.post(f"/v1/sources/{src}/items", json=b) for b in body), return_exceptions=True)
        data(await client.post(f"/v1/sources/{src}/sync"))
        held = data(await client.get(f"/v1/sources/{src}"))["config"]["fileIds"]
    counts = {fid: f["referenceCount"] for fid, f in fake.files.items()}
    assert counts == {fid: int(fid in held) for fid in counts} and len(held) == 1, (held, counts)


async def test_a_refused_new_version_leaves_the_indexed_one_answering_search(engine: AsyncEngine, tenant: str) -> None:
    """A refused scan of a new version marked the indexed item failed under the refused file, so the good earlier
    version stopped answering search. It keeps answering, and the item and the run say the new version was refused."""
    fake = FakeFilesService()
    async with kb_client(engine, tenant, files=FilesServiceIntake(fake.client())) as client:
        kb = data(
            await client.post("/v1/knowledge-bases", json={"name": "Disputes", "owner": "james@harborpine.example"}),
            201,
        )
        src = data(await client.post("/v1/sources", json={"type": "push", "name": "Rules", "kbIds": [kb["id"]]}), 201)
        for text, verdict in (
            ("Chargebacks are raised within 120 days.", "clean"),
            ("Chargebacks are raised within 90 days.", "infected"),
        ):
            await client.post(
                f"/v1/sources/{src['id']}/items", json={"name": "window", "title": "Window", "text": text}
            )
            await scan_all(fake, tenant, verdict)
            run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
        item = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"][0]
        found = data(await client.post(f"/v1/knowledge-bases/{kb['id']}/query", json={"question": "chargeback days"}))
    assert run["counts"]["failed"] == 1 and run["errors"][0]["errorClass"] == "scan", run
    assert item["status"] == "indexed" and "infected" in (item.get("warning") or ""), item
    assert found["chunks"] and "120 days" in found["chunks"][0]["text"], found


class _MidSync(FilesServiceIntake):
    """kb-service's Files adapter that runs `during` once, as the sync takes its reference on a new version."""

    during: Callable[[], Awaitable[object]] | None = None

    async def use(self, tenant: str, team: str, file_id: str, *, source_id: str, source_name: str) -> str:
        if (during := self.during) is not None:
            self.during = None
            await during()
        return await super().use(tenant, team, file_id, source_id=source_id, source_name=source_name)


async def _two_versions(
    engine: AsyncEngine, tenant: str, during: Callable[[AsyncClient, str], Awaitable[object]]
) -> tuple[FakeFilesService, str, list[str]]:
    """Writes window at 120 days, then at 90 days with `during` run as that sync reads the new version; the 120-day
    file's id and the files the source holds after."""
    fake = _ScannedAtOnce()
    intake = _MidSync(fake.client())
    async with kb_client(engine, tenant, files=intake) as client:
        src = await push_source(client)
        first = {"name": "window", "title": "W", "text": "Raised within 120 days."}
        data(await client.post(f"/v1/sources/{src}/items", json=first))
        old = data(await client.get(f"/v1/sources/{src}"))["config"]["fileIds"][0]
        intake.during = lambda: during(client, src)
        await client.post(f"/v1/sources/{src}/items", json={**first, "text": "Raised within 90 days."})
        held = data(await client.get(f"/v1/sources/{src}"))["config"]["fileIds"]
    return fake, old, held


async def test_earlier_content_sent_again_during_a_sync_stays_held(engine: AsyncEngine, tenant: str) -> None:
    """A sync dropped and released the files it read as replaced at its start, so earlier content sent again under the
    same name while it ran lost the file that was now the name's newest."""

    async def resend(client: AsyncClient, src: str) -> None:
        await client.post(
            f"/v1/sources/{src}/items", json={"name": "window", "title": "W", "text": "Raised within 120 days."}
        )

    fake, old, held = await _two_versions(engine, tenant, resend)
    assert held[-1] == old and fake.files[old]["referenceCount"] == 1, (held, fake.files)


async def test_a_sync_that_lost_its_lease_lets_go_of_nothing(engine: AsyncEngine, tenant: str) -> None:
    """A sync whose lease another run took still dropped and released the files it saw as replaced."""

    async def taken(_client: AsyncClient, src: str) -> None:
        async with engine.begin() as c:
            await c.execute(sa.update(kb_sources).where(kb_sources.c.id == src).values(lease_owner="lease_other"))

    fake, old, held = await _two_versions(engine, tenant, taken)
    assert old in held and fake.files[old]["referenceCount"] == 1, (held, fake.files)


async def test_a_sync_that_lost_its_lease_is_recorded_as_stopped(engine: AsyncEngine, tenant: str) -> None:
    """A sync that lost its lease stopped reading but still removed excluded items and recorded success."""
    fake = _ScannedAtOnce()
    intake = _MidSync(fake.client())
    async with kb_client(engine, tenant, files=intake) as client:
        src = await push_source(client)
        first = {"name": "window", "title": "W", "text": "Raised within 120 days."}
        data(await client.post(f"/v1/sources/{src}/items", json=first))

        async def taken() -> None:
            async with engine.begin() as c:
                await c.execute(sa.update(kb_sources).where(kb_sources.c.id == src).values(lease_owner="lease_other"))

        intake.during = taken
        await client.post(f"/v1/sources/{src}/items", json={**first, "text": "Raised within 90 days."})
        runs = data(await client.get(f"/v1/sources/{src}/runs"))["data"]
    assert runs[0]["status"] == "cancelled" and any("lease" in x for x in runs[0]["log"]), runs[0]


async def test_earlier_content_sent_again_after_a_refused_version_clears_the_scan_note(
    engine: AsyncEngine, tenant: str
) -> None:
    """The note that a newer version was refused stayed on the item after the earlier content was sent again."""
    fake = FakeFilesService()
    async with kb_client(engine, tenant, files=FilesServiceIntake(fake.client())) as client:
        src = await push_source(client)
        body = {"name": "window", "title": "Window", "text": "Raised within 120 days."}
        for text, verdict in (("Raised within 120 days.", "clean"), ("Raised within 90 days.", "infected")):
            await client.post(f"/v1/sources/{src}/items", json={**body, "text": text})
            await scan_all(fake, tenant, verdict)
            data(await client.post(f"/v1/sources/{src}/sync"))
        assert "infected" in (data(await client.get(f"/v1/sources/{src}/items"))["data"][0].get("warning") or "")
        again = data(await client.post(f"/v1/sources/{src}/items", json=body))["item"]
    assert again["status"] == "indexed" and "infected" not in (again.get("warning") or ""), again


class _NoRelease(FakeFilesService):
    """A Files that refuses every release of a reference."""

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE" and "/references/" in request.url.path:
            return httpx.Response(503, json={"success": False, "error": {"code": "unavailable", "message": "down"}})
        return super().handle(request)


async def test_a_refused_add_reports_its_own_refusal_and_leaves_no_documents_source(
    engine: AsyncEngine, tenant: str
) -> None:
    """A release Files refused during the rollback of a refused add replaced the refusal with a 503, stopped the
    rollback, and left the base an empty documents source."""
    fake = _NoRelease()
    files = fake.client()
    async with kb_client(engine, tenant, files=FilesServiceIntake(files)) as client:
        kb = data(
            await client.post("/v1/knowledge-bases", json={"name": "Disputes", "owner": "james@harborpine.example"}),
            201,
        )
        fid = await stored(fake, files, tenant, "rates.pdf", RATES)
        r = await client.post(f"/v1/knowledge-bases/{kb['id']}/documents", json={"fileIds": [fid, "fil_none"]})
        sources = data(await client.get("/v1/sources"))["data"]
    assert r.status_code == 404 and r.json()["error"]["code"] != "files_unavailable", r.text
    assert not [x for x in sources if kb["id"] in (x.get("kbIds") or [])], sources


async def test_a_source_whose_files_cannot_be_released_is_kept_to_retry(engine: AsyncEngine, tenant: str) -> None:
    """Removing a source deleted its row and then released its files, so a release Files refused left a file held
    for a source that no longer existed. The source stays, the caller can retry, and the retry lets go of all."""
    fake = FakeFilesService()
    async with kb_client(engine, tenant, files=FilesServiceIntake(fake.client())) as client:
        src = await push_source(client)
        await client.post(
            f"/v1/sources/{src}/items", json={"name": "window", "title": "W", "text": "Raised in 120 days."}
        )
        await scan_all(fake, tenant)
        data(await client.post(f"/v1/sources/{src}/sync"))
        fake.refuse = 401
        refused = await client.delete(f"/v1/sources/{src}")
        fake.refuse = None
        assert refused.status_code == 503, refused.text
        assert (await client.get(f"/v1/sources/{src}")).status_code == 200, (
            "the source stays while Files holds its files"
        )
        assert (await client.delete(f"/v1/sources/{src}")).status_code == 204
    assert all(f["referenceCount"] == 0 for f in fake.files.values()), fake.files


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
