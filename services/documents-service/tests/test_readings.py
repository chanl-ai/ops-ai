"""Readings, by failure mode: a file's bytes read again for a second caller or a second purpose; an old reading served
after the reader changed; another team given the reading of a file it cannot see; a scan read inside the request, or
never reported when it ends; a long read starting over after a restart; one team's bulk upload holding up another's;
OCR missing with nothing saying so; a reading kept after the last file holding its bytes is deleted; a file with no
reader failing without a reason; and the layout routes drifting from the reading they are drawn from."""

from __future__ import annotations

import io
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy.ext.asyncio import AsyncEngine

import ops_documents.app as documents_app
from ops_documents import readings as readings_module
from ops_documents.readings import Readings, next_reading, settings_of
from ops_documents.store import ReadingsStore
from ops_documents.store.event_relay import sender
from ops_documents.store.extractions import service_outbox
from ops_documents.store.readings import ReadingRow
from ops_files_client.testing import FakeFilesService
from ops_identity import dev_service_signer, mint_service_token
from ops_ingest.reading import READER_VERSION, read
from ops_store import isolation

from .conftest import OPS, Make
from .test_extractions import NOTICE, Floor, Models

SCANNED = Path(__file__).resolve().parents[3] / "packages" / "ops_ingest" / "tests" / "fixtures" / "scanned.pdf"
requires_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not on PATH")


@pytest.fixture
def content_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each time a file's bytes are read from the faked files-service, by file id."""
    seen: list[str] = []
    real = FakeFilesService.handle

    def counted(self: FakeFilesService, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/content"):
            seen.append(request.url.path.split("/")[3])
        return real(self, request)

    monkeypatch.setattr(FakeFilesService, "handle", counted)
    return seen


def token(tenant: str, *scopes: str, team: str = "team_ops") -> dict[str, str]:
    t = mint_service_token(
        dev_service_signer(),
        service="agents",
        audience="documents",
        tenant_id=tenant,
        scopes=list(scopes),
        team_id=team,
    )
    return {"Authorization": f"Bearer {t}"}


def pages_pdf(count: int) -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    for n in range(1, count + 1):
        c.drawString(72, 700, f"Section {n} of the overdraft policy")
        c.showPage()
    c.save()
    return buf.getvalue()


async def ask(c: httpx.AsyncClient, file_id: str, headers: dict[str, str] = OPS, **body: Any) -> httpx.Response:
    return await c.post("/v1/documents/readings", json={"fileId": file_id, **body}, headers=headers)


async def test_a_second_read_of_the_same_bytes_reads_nothing(make: Make, content_reads: list[str]) -> None:
    s = make(Models(), Floor())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        first = await ask(c, fid)
        again = await ask(c, fid)
        layout = await c.post("/v1/documents/layout", json={"fileId": fid, "ocr": True}, headers=OPS)
    body = first.json()["data"]
    assert first.status_code == 200 and body["status"] == "done", first.text
    assert body["pages"][0]["text"].startswith("Invoice INV-2207") and body["readerVersion"] == READER_VERSION
    assert again.json()["data"]["pages"] == body["pages"] and layout.status_code == 200
    assert content_reads == [fid], "read once; the second ask and the layout come from the stored reading"


async def test_a_changed_reader_reads_the_bytes_again(
    make: Make, content_reads: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    s = make(Models(), Floor())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        await ask(c, fid)
        monkeypatch.setattr(readings_module, "READER_VERSION", "reading-test")
        changed = (await ask(c, fid)).json()["data"]
    assert changed["readerVersion"] == "reading-test" and content_reads == [fid, fid], content_reads


async def test_another_teams_file_has_no_reading_though_its_bytes_are_read(make: Make) -> None:
    s = make(Models(), Floor())
    async with s.client as c:
        mine = await s.stored(NOTICE)
        theirs = await s.stored(NOTICE, team="team_cards")
        await ask(c, mine)
        other = await ask(c, theirs)
        peek = await c.get(f"/v1/documents/readings/{theirs}", headers=OPS)
    assert other.status_code == 404 and peek.status_code == 404, (other.text, peek.text)


@requires_tesseract
async def test_a_scan_is_read_in_the_background_and_reported(make: Make, engine: AsyncEngine) -> None:
    s = make(Models(), Floor())
    async with s.client as c:
        fid = await s.stored(SCANNED.read_bytes(), name="scanned.pdf", mime="application/pdf")
        asked = await ask(c, fid)
        readings = s.extractor.readings
        assert readings is not None
        await readings.drain()
        done = (await c.get(f"/v1/documents/readings/{fid}", headers=OPS)).json()["data"]
        page = (await c.get(f"/v1/documents/readings/{fid}", params={"page": 1}, headers=OPS)).json()["data"]
    assert asked.status_code == 202 and asked.json()["data"]["status"] == "queued", asked.text
    assert done["status"] == "done" and done["pages"][0]["source"] == "ocr", done
    assert "LATE PAYMENT FEE" in page["pages"][0]["text"].upper() and len(page["pages"]) == 1
    async with engine.connect() as conn:
        mine = service_outbox.c.tenant_id == s.tenant
        events = (await conn.execute(sa.select(service_outbox.c.name, service_outbox.c.payload).where(mine))).all()
    finished = [p for n, p in events if n == "reading.finished"]
    assert [(p["fileId"], p["settingsKey"]) for p in finished] == [(fid, "auto:eng")], events


async def test_a_long_read_carries_on_from_its_next_page_after_a_restart(
    make: Make, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = make(Models(), Floor())
    data = pages_pdf(8)
    async with s.client as c:
        fid = await s.stored(data, name="policy.pdf", mime="application/pdf")
        info = await s.files.client(service="documents").get(s.tenant, "team_ops", fid)
        whole = read(data, filename="policy.pdf", settings=settings_of("auto"))
        store = ReadingsStore(engine)
        with isolation.scope(s.tenant, "team_ops"):
            row = await store.queue(
                info.digest, READER_VERSION, "auto:eng", file_id=fid, team="team_ops", actor="x", at=_now()
            )
            await store.link(fid, "team_ops", info.digest, _now())
            await store.start(row, at=_now())
            await store.opened(row, pages_total=8, facts=whole.facts.model_dump(mode="json", by_alias=True))
            for page in whole.pages[:3]:
                await store.save_page(row, page.number, page.model_dump(mode="json", by_alias=True))
        # The process stopped after page 3; a new one starts and resumes.
        pages_read: list[int] = []
        real_open = readings_module.open_file

        def watched(*args: Any, **kw: Any) -> Any:
            opened = real_open(*args, **kw)
            reader = opened.__enter__()
            real_page = reader.page

            def page(n: int) -> Any:
                pages_read.append(n)
                return real_page(n)

            reader.page = page  # pyright: ignore[reportAttributeAccessIssue]
            return _Entered(opened, reader)

        monkeypatch.setattr(readings_module, "open_file", watched)
        restarted = Readings(s.extractor.files, store)
        assert await restarted.resume() == 1
        await restarted.drain()
        done = (await c.get(f"/v1/documents/readings/{fid}", headers=OPS)).json()["data"]
    assert pages_read == [4, 5, 6, 7, 8], pages_read
    assert done["status"] == "done" and [p["number"] for p in done["pages"]] == list(range(1, 9)), done


class _Entered:
    def __init__(self, cm: Any, reader: Any) -> None:
        self.cm, self.reader = cm, reader

    def __enter__(self) -> Any:
        return self.reader

    def __exit__(self, *exc: object) -> None:
        self.cm.__exit__(*exc)


def _now() -> Any:
    from datetime import UTC, datetime  # noqa: PLC0415

    return datetime.now(UTC)


def _row(team: str, n: int) -> ReadingRow:
    return ReadingRow(
        "t", f"d{team}{n}", READER_VERSION, "auto:eng", "queued", None, 0, None, None, None, 0, "f", team, "x", None
    )


def test_one_teams_bulk_upload_does_not_hold_up_another() -> None:
    queued = [*(_row("team_a", n) for n in range(50)), _row("team_b", 0)]
    started: list[str] = []
    running: list[str] = []
    while len(started) < 3:
        i = next_reading(queued, running)
        assert i is not None
        row = queued.pop(i)
        started.append(row.team)
        running.append(row.team)
        if len(running) == 2:
            running.pop(0)  # the oldest of the two slots ends
    assert started.index("team_b") < 2, started


async def test_health_says_degraded_without_ocr(make: Make, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documents_app, "ocr_installed", lambda: False)
    s = make(Models(), Floor())
    async with s.client as c:
        health = await c.get("/health")
    assert health.status_code == 200 and health.json() == {"status": "degraded", "reason": "ocr"}, health.text


async def test_a_reading_goes_with_the_teams_last_file_of_its_bytes(make: Make) -> None:
    s = make(Models(), Floor())
    risk = token(s.tenant, "documents:run", team="team_risk")
    async with s.client as c:
        mine = await s.stored(NOTICE)
        theirs = await s.stored(NOTICE, team="team_risk")
        await ask(c, mine)
        await ask(c, theirs, headers=risk)
        s.files.files.pop(mine)
        gone = await c.post("/v1/documents/purge", json={"fileId": mine}, headers=token(s.tenant, "documents:delete"))
        kept = await c.get(f"/v1/documents/readings/{theirs}", headers={"X-Team-Id": "team_risk"})
    assert gone.status_code == 200 and gone.json()["data"]["readings"] == 1, gone.text
    assert kept.json()["data"]["status"] == "done", "another team's reading of the same bytes is its own"


async def test_a_file_with_no_reader_fails_with_its_reason(make: Make) -> None:
    s = make(Models(), Floor())
    async with s.client as c:
        fid = await s.stored(b"PK\x03\x04 not a deck", name="deck.pptx", mime="application/octet-stream")
        body = (await ask(c, fid)).json()["data"]
    assert body["status"] == "failed" and body["error"]["code"] == "unsupported_format", body


async def test_reading_events_go_to_kb_and_extraction_events_to_agents() -> None:
    sent: dict[str, list[str]] = {"agents": [], "kb": []}

    class Client:
        def __init__(self, name: str) -> None:
            self.name = name

        async def post(self, path: str, body: dict[str, Any], **_: Any) -> None:
            sent[self.name].append(str(body["name"]))

    send = sender(Client("agents"), Client("kb"))  # pyright: ignore[reportArgumentType]
    for name in ("reading.finished", "extraction.finished", "reading.failed"):
        await send({"tenantId": "t", "body": {"name": name, "teamId": "team_ops"}})
    assert sent == {"agents": ["extraction.finished"], "kb": ["reading.finished", "reading.failed"]}, sent


async def test_the_layout_is_drawn_from_the_reading(make: Make) -> None:
    s = make(Models(), Floor())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        before = (await c.get(f"/v1/documents/layout/{fid}", headers=OPS)).json()["data"]
        layout = (await c.post("/v1/documents/layout", json={"fileId": fid}, headers=OPS)).json()["data"]
        page = (await c.get(f"/v1/documents/layout/{fid}", params={"page": 1}, headers=OPS)).json()["data"]
        reading = (await c.get(f"/v1/documents/readings/{fid}", params={"ocr": "off"}, headers=OPS)).json()["data"]
    assert before is None and page["blocks"] == layout["blocks"], page
    assert layout["blocks"][0]["text"] == reading["pages"][0]["blocks"][0]["text"], (layout, reading)
