"""The extraction API (c-235, moved here in c-256), by failure mode: a field's confidence or review set by anyone but
the checks, or below the workspace floor (F1); a large extraction lost on restart (F2); a correction that erases the
original (F3); another team's file, an unscanned one or an unknown document type read, or an unreadable floor lowering
the bar (F5); a provider called directly, an unbound `extract` alias failing instead of using `default`, or the tenant
left off the model call (F6); and what a deleted file leaves behind (the purge). files-service is faked at its
routes."""

from __future__ import annotations

import io
import json
from typing import Any

import httpx
import sqlalchemy as sa
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents import extraction
from ops_documents.extraction import ModelsService
from ops_documents.store.extractions import service_outbox
from ops_extract.floor import FloorUnreadError
from ops_identity import dev_service_signer, mint_service_token

from .conftest import OPS, Make

NOTICE = b"Invoice INV-2207\nAmount due: 1,250.00 CAD\nCustomer: Marcus Bell\n"
FIELDS = [
    {"key": "invoice", "label": "Invoice number", "type": "text", "required": True},
    {"key": "amount", "type": "money", "required": True},
]
GOOD = {
    "invoice": {"value": "INV-2207", "quote": "Invoice INV-2207", "page": 1},
    "amount": {"value": "1,250.00 CAD", "quote": "Amount due: 1,250.00 CAD", "page": 1},
}


class Models:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, str]] = []

    async def structured(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        run: str,
        step: str,
        tenant: str,
        usage: Any = None,
        images: Any = (),
    ) -> Any:
        self.calls.append((step, tenant))
        return self.answers.pop(0) if self.answers else GOOD


class Floor:
    def __init__(self, value: float | None = 0.8) -> None:
        self.value = value

    async def floor(self, tenant: str, team: str) -> float:
        if self.value is None:
            raise FloorUnreadError("The extractionFloor policy could not be read: 503")
        return self.value


async def extract(
    c: httpx.AsyncClient, file_id: str, headers: dict[str, str] | None = None, **body: Any
) -> httpx.Response:
    return await c.post(
        "/v1/documents/extractions", json={"fileId": file_id, "fields": FIELDS, **body}, headers=headers or OPS
    )


async def test_fields_are_scored_by_the_checks_against_the_highest_threshold(make: Make) -> None:
    invented = {**GOOD, "invoice": {"value": "INV-9999", "quote": "Invoice INV-9999", "page": 1}}
    models = Models(invented)
    s = make(models, Floor(0.95))
    async with s.client as c:
        r = await extract(c, await s.stored(NOTICE), reviewBelow=0.5)
    body = r.json()["data"]
    assert r.status_code == 200 and body["status"] == "done" and body["outcome"] == "review", body
    # A quote the page does not hold scores 0; the amount, normalised, scores 0.9: below the floor of 0.95.
    fields = body["fields"]
    assert (fields["invoice"]["confidence"], fields["amount"]["confidence"], body["floor"]) == (0, 0.9, 0.95), body
    assert body["needsReview"] == ["invoice", "amount"], body
    assert models.calls == [("extract", s.tenant)], "the tenant rides on the model call (c-251)"


async def test_a_queued_extraction_runs_again_after_a_restart(make: Make, monkeypatch: Any) -> None:
    monkeypatch.setattr(extraction, "SYNC_BYTES", 10)  # every file is large: queued, run as a task
    first = make(Models(), Floor())
    monkeypatch.setattr(first.extractor, "_later", _stopped)  # this process stops before the task runs
    async with first.client as c:
        queued = (await extract(c, await first.stored(NOTICE))).json()["data"]
    assert queued["status"] == "queued", queued
    restarted = make(Models(), Floor())
    restarted.files.files, restarted.files.blobs = first.files.files, first.files.blobs
    async with restarted.client as c, restarted.app.router.lifespan_context(restarted.app):
        await restarted.extractor.drain()
        body = (await c.get(f"/v1/documents/extractions/{queued['id']}", headers=OPS)).json()["data"]
    assert body["status"] == "done" and body["fields"]["amount"]["value"] == 1250.0, body


def _stopped(row: Any) -> None:
    return None


async def test_a_correction_keeps_the_original_value_and_confidence(make: Make) -> None:
    s = make(Models(), Floor())
    async with s.client as c:
        done = (await extract(c, await s.stored(NOTICE))).json()["data"]
        r = await c.patch(f"/v1/documents/extractions/{done['id']}/fields/amount", json={"value": 1205.0}, headers=OPS)
    body = r.json()["data"]
    [fix] = body["corrections"]
    assert body["fields"]["amount"]["value"] == 1205.0 and body["fields"]["amount"]["corrected"], body
    assert (fix["original"], fix["originalConfidence"], fix["corrected"]) == (1250.0, 0.9, 1205.0), fix


async def test_another_teams_file_an_unscanned_one_an_unread_floor_and_an_unknown_type_are_refused(make: Make) -> None:
    s = make(Models(), Floor(None))
    async with s.client as c:
        theirs = await extract(c, await s.stored(NOTICE, team="team_cards"))
        pending = await extract(c, await s.stored(NOTICE + b"\n", clean=False))
        unread = (await extract(c, await s.stored(NOTICE + b"\n\n"))).json()["data"]
        typed = await c.post(
            "/v1/documents/extractions", json={"fileId": "fil_0001", "documentTypeId": "nope"}, headers=OPS
        )
    assert theirs.status_code == 404 and theirs.json()["error"]["message"] == "File was not found.", theirs.text
    assert pending.status_code == 409, pending.text
    assert unread["status"] == "failed" and unread["error"]["code"] == "floor_unread" and "fields" not in unread
    assert typed.status_code == 404 and typed.json()["error"]["message"] == "Document type was not found.", typed.text


async def test_a_retry_with_the_same_key_is_the_same_extraction_and_a_failed_one_runs_again(make: Make) -> None:
    floor = Floor(None)
    models = Models()
    s = make(models, floor)
    async with s.client as c:
        fid = await s.stored(NOTICE)
        key = {**OPS, "Idempotency-Key": "run_1:read:0"}
        failed = (await extract(c, fid, headers=key)).json()["data"]
        floor.value = 0.8
        again = (await extract(c, fid, headers=key)).json()["data"]
        same = (await extract(c, fid, headers=key)).json()["data"]
    assert failed["status"] == "failed" and (again["id"], again["status"]) == (failed["id"], "done"), again
    assert same["id"] == failed["id"] and len(models.calls) == 2, models.calls


async def test_only_a_service_purges_and_only_a_deleted_files_reads_of_its_team(
    make: Make,
) -> None:
    s = make(Models(), Floor())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        done = (await extract(c, fid)).json()["data"]

        def token(*scopes: str, team: str = "team_ops") -> dict[str, str]:
            t = mint_service_token(
                dev_service_signer(),
                service="agents",
                audience="documents",
                tenant_id=s.tenant,
                scopes=list(scopes),
                team_id=team,
            )
            return {"Authorization": f"Bearer {t}"}

        refused = await extract(c, fid, headers=token("files:view"))
        allowed = await extract(c, fid, headers=token("documents:run"))
        person_purge = await c.post("/v1/documents/purge", json={"fileId": fid}, headers=OPS)
        live = await c.post("/v1/documents/purge", json={"fileId": fid}, headers=token("documents:delete"))
        s.files.files.pop(fid)
        other_team = await c.post(
            "/v1/documents/purge", json={"fileId": fid}, headers=token("documents:delete", team="team_risk")
        )
        purged = await c.post("/v1/documents/purge", json={"fileId": fid}, headers=token("documents:delete"))
        gone = await c.get(f"/v1/documents/extractions/{done['id']}", headers=OPS)
    assert refused.status_code == 403 and allowed.status_code == 200, (refused.text, allowed.text)
    assert person_purge.status_code == 403, person_purge.text
    assert live.status_code == 409, "a purge of a file files-service still serves removes nothing"
    assert other_team.json()["data"]["extractions"] == 0, "another team's purge leaves this team's reads"
    assert purged.json()["data"]["extractions"] == 2 and gone.status_code == 404, (purged.text, gone.text)


async def test_models_service_is_asked_on_extract_then_default_with_the_tenant() -> None:
    seen: list[tuple[str, str, str | None]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((body["model"], request.headers["authorization"], request.headers.get("x-tenant-id")))
        if body["model"] == "extract":
            return httpx.Response(404, json={"error": {"code": "alias_not_found"}})
        call = {"function": {"name": "final_result", "arguments": json.dumps(GOOD)}}
        return httpx.Response(200, json={"choices": [{"message": {"content": None, "tool_calls": [call]}}]})

    http = httpx.AsyncClient(base_url="http://models", transport=httpx.MockTransport(answer))
    got = await ModelsService(http, "key").structured("s", "u", {}, run="ext_1", step="extract", tenant="t_bank")
    assert got == GOOD and seen == [("extract", "Bearer key", "t_bank"), ("default", "Bearer key", "t_bank")]


async def test_a_files_extractions_list_newest_first_for_the_team_and_another_teams_file_is_not_found(
    make: Make,
) -> None:
    """The file page's Fields tab (c-250) reads a file's extractions in one call, paged, newest first."""
    s = make(Models(), Floor())
    async with s.client as c:
        fid = await s.stored(NOTICE)
        first = (await extract(c, fid)).json()["data"]["id"]
        second = (await extract(c, fid, reviewBelow=0.5)).json()["data"]["id"]
        listed = (await c.get("/v1/documents/extractions", params={"fileId": fid, "pageSize": 1}, headers=OPS)).json()
        theirs = await c.get("/v1/documents/extractions", params={"fileId": fid}, headers={"X-Team-Id": "team_cards"})
    assert [e["id"] for e in listed["data"]["data"]] == [second] and first != second, listed
    assert listed["data"]["pagination"]["total"] == 2 and listed["data"]["pagination"]["hasNext"] is True
    assert theirs.status_code == 404, theirs.text


async def test_a_pdf_fields_value_carries_its_box_on_the_page_and_an_invented_one_none(make: Make) -> None:
    """Through the API from a real PDF (c-252): the file page draws each field where its value is printed."""
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    for i, line in enumerate(NOTICE.decode().splitlines()):
        c.drawString(72, LETTER[1] - 100 - 16 * i, line)
    c.save()
    invented = {**GOOD, "invoice": {"value": "INV-9999", "quote": "Invoice INV-9999", "page": 1}}
    s = make(Models(invented), Floor())
    async with s.client as cl:
        fid = await s.stored(buf.getvalue(), name="notice.pdf", mime="application/pdf")
        body = (await extract(cl, fid)).json()["data"]
    amount, invoice = body["fields"]["amount"], body["fields"]["invoice"]
    [box] = amount["boxes"]
    assert box["page"] == 1 and box["x"] > 72 / LETTER[0] + 0.05 and abs(box["y"] - (116 - 10) / LETTER[1]) < 0.01, box
    assert amount["blocks"] and "boxes" not in invoice, body


async def test_every_end_of_a_read_reports_extraction_finished_once_with_its_outcome(
    make: Make, engine: AsyncEngine, monkeypatch: Any
) -> None:
    """A workflow step parked on a long read resumes on extraction.finished (c-525), so a read that ends without it
    leaves the run waiting until its time limit. One event per extraction, keyed by its id, for done, failed and
    unreadable alike, written in the transaction that ends the read."""
    monkeypatch.setattr(extraction, "SYNC_BYTES", 10)  # every file is read in the background
    s = make(Models(), Floor())
    async with s.client as c, s.app.router.lifespan_context(s.app):
        done = (await extract(c, await s.stored(NOTICE))).json()["data"]
        await s.extractor.drain()
        failing = make(_DownModels(), Floor())
        failing.files.files, failing.files.blobs = s.files.files, s.files.blobs
    async with failing.client as c2, failing.app.router.lifespan_context(failing.app):
        failed = (await extract(c2, await failing.stored(b"Another notice, read by a model that is down\n"))).json()[
            "data"
        ]
        await failing.extractor.drain()
    async with engine.connect() as conn:
        o = service_outbox
        q = sa.select(o.c.event_key, o.c.team_id, o.c.payload).where(
            o.c.tenant_id == s.tenant, o.c.name == "extraction.finished"
        )
        rows = {r.event_key: r for r in (await conn.execute(q)).all()}
    assert set(rows) == {done["id"], failed["id"]}, rows
    assert rows[done["id"]].payload["status"] == "done" and rows[done["id"]].payload["fileId"] == done["fileId"], rows
    assert rows[failed["id"]].payload["status"] == "failed", rows


class _DownModels(Models):
    """A model that is out of reach on every call."""

    async def structured(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("model down")
