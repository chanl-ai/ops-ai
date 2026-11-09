"""File sources indexed from documents-service's readings, by failure mode: a scanned PDF still indexing empty; a scan
holding up the sync, or its item never indexed once the reading ends (the event lost or never sent); documents-service
down failing the sync; a full re-index reading the file's bytes again; an event from another team settling this
team's items; and a filled form's typed values staying unsearchable. Readings are made by the one reader in this
process (readings_fake.LocalReadings), so each test splits the reading a real documents-service gives."""

from __future__ import annotations

import io
import shutil
from typing import Any

import httpx
import pytest
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import dev_service_signer, mint_service_token
from ops_identity.fastapi import DEV_TEAM
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_kb.agents import StaticAgents
from ops_kb.files import KnowledgeFiles
from ops_kb.schedule import finish_readings
from ops_kb.service import KnowledgeService
from ops_kb.store import KnowledgeStore
from ops_kb.store.fulltext import PostgresFullTextRetriever

from .conftest import kb_client
from .pdfs import RATES, scanned_pdf
from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_retrieval import ask
from .test_sync import file_source, upload

requires_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not on PATH")


def documents(tenant: str, team: str = DEV_TEAM, scopes: tuple[str, ...] = ("events:emit",)) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="documents", audience="kb", tenant_id=tenant, ttl_s=TEST_TOKEN_TTL_S,
        scopes=list(scopes), team_id=team,
    )  # fmt: skip
    return {"Authorization": f"Bearer {token}"}


async def base_with(client: httpx.AsyncClient, *files: tuple[str, bytes]) -> tuple[dict[str, Any], dict[str, Any]]:
    src = await file_source(client)
    body = {"name": "Lending", "owner": "maya@harborpine.example", "sourceIds": [src["id"]]}
    kb = data(await client.post("/v1/knowledge-bases", json=body), 201)
    for name, pdf in files:
        await upload(client, src["id"], name, pdf)
    return src, kb


def filled_form() -> bytes:
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=LETTER)
    canvas.drawString(50, 700, "Member enrolment form")
    canvas.drawString(50, 660, "Policy number:")
    canvas.acroForm.textfield(name="policy_number", value="PL-90385217", x=160, y=656, width=200, height=16)  # pyright: ignore[reportUnknownMemberType]
    canvas.showPage()
    canvas.save()
    return out.getvalue()


@requires_tesseract
async def test_a_scanned_pdf_is_searchable_and_its_item_says_ocr_read_it(client: httpx.AsyncClient) -> None:
    src, kb = await base_with(client, ("scan.pdf", scanned_pdf()))
    run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
    item = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"][0]
    answer = await ask(client, kb["id"], "What is the late payment fee?")
    assert (run["counts"]["upserted"], item["status"]) == (1, "indexed"), (run, item)
    assert "Page 1 was read by OCR" in (item["warning"] or ""), item
    assert answer["citations"] and answer["citations"][0]["page"] == 1, answer


async def test_a_scan_being_read_does_not_hold_up_the_sync_and_is_indexed_on_its_event(
    engine: AsyncEngine, tenant: str, tmp_path: Any
) -> None:
    intake = KnowledgeFiles(tmp_path)
    readings = LocalReadings(intake)
    async with kb_client(engine, tenant, files=intake, readings=readings) as client:
        src, kb = await base_with(client, ("rates.pdf", RATES))
        fid = next(iter(data(await client.get(f"/v1/sources/{src['id']}"))["config"]["fileIds"]))
        readings.pending[fid] = 1
        run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
        waiting = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"][0]
        event = {
            "name": "reading.finished",
            "key": f"reading.finished:{fid}",
            "teamId": DEV_TEAM,
            "payload": {"fileId": fid},
        }
        other = await client.post(
            "/v1/events", json={**event, "teamId": "team_other"}, headers=documents(tenant, "team_other")
        )
        done = await client.post("/v1/events", json=event, headers=documents(tenant))
        again = await client.post("/v1/events", json=event, headers=documents(tenant))
        item = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"][0]
        answer = await ask(client, kb["id"], "five-year fixed mortgage rate for insured borrowers")
    assert (run["counts"]["reading"], waiting["status"]) == (1, "reading"), (run, waiting)
    assert other.json()["data"]["items"] == 0, "another team's event settles none of this team's items"
    assert done.status_code == 202 and done.json()["data"]["items"] == 1, done.text
    assert again.json()["data"]["items"] == 0 and (item["status"], item["version"]) == ("indexed", "v1"), item
    assert answer["citations"], answer


async def test_an_item_whose_event_never_came_is_indexed_by_the_schedule(
    engine: AsyncEngine, tenant: str, tmp_path: Any
) -> None:
    intake = KnowledgeFiles(tmp_path)
    readings = LocalReadings(intake)
    async with kb_client(engine, tenant, files=intake, readings=readings) as client:
        src, _ = await base_with(client, ("rates.pdf", RATES))
        readings.down = True
        run = data(await client.post(f"/v1/sources/{src['id']}/sync"))
        readings.down = False
        before = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"][0]
    assert (run["status"], run["counts"]["reading"], before["status"]) == ("success", 1, "reading"), run
    service = KnowledgeService(
        KnowledgeStore(engine), intake, PostgresFullTextRetriever(engine), StaticAgents(), readings=readings
    )
    assert await finish_readings(service) == 1
    async with kb_client(engine, tenant, files=intake, readings=readings) as client:
        item = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"][0]
    assert item["status"] == "indexed", item


async def test_a_full_reindex_splits_the_stored_reading_without_reading_the_file(
    engine: AsyncEngine, tenant: str, tmp_path: Any
) -> None:
    intake = KnowledgeFiles(tmp_path)
    readings = LocalReadings(intake)
    reads: list[str] = []
    real = intake.read

    async def counted(tenant: str, team: str, file_id: str) -> tuple[str, str, bytes]:
        reads.append(file_id)
        return await real(tenant, team, file_id)

    intake.read = counted  # type: ignore[method-assign]
    async with kb_client(engine, tenant, files=intake, readings=readings) as client:
        src, _ = await base_with(client, ("rates.pdf", RATES))
        added = len(reads)  # the folder store reads a file once to name it when it is added
        data(await client.post(f"/v1/sources/{src['id']}/sync"))
        full = data(await client.post(f"/v1/sources/{src['id']}/sync", json={"full": True}))
    assert full["counts"]["upserted"] == 1 and len(reads) - added == 1, (full, reads)


async def test_a_filled_forms_typed_value_is_searchable(client: httpx.AsyncClient) -> None:
    src, kb = await base_with(client, ("enrolment.pdf", filled_form()))
    data(await client.post(f"/v1/sources/{src['id']}/sync"))
    answer = await ask(client, kb["id"], "policy_number PL-90385217")
    assert answer["citations"] and "PL-90385217" in answer["citations"][0]["snippet"], answer
