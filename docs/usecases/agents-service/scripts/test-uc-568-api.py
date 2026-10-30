# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-568 document workflows, api layer: docs/usecases/agents-service/document-workflows.md (c-535).

Own services, no real model: models-service on the fake OpenAI with rules this script writes to a temporary folder (a
propose read and the read after it), files-service with scanning off delivering its events to this run's
agents-service, documents-service with the seeded document types, agents-service holding Files and documents routes,
and a workflow worker. The scan is 12 pages of images built here with Pillow and reportlab, read with Tesseract.

A builder reads the scan as full text with no model call and only the pages asked for, lets the model propose fields
and saves them as a document type, shares a workflow as a form that refuses a rotated link, a non-member, a flood and
a day past its cap, runs a workflow once per row of a CSV with a dry run first and Retry failed rows, and a run of
Combine facts whose sources disagree leaves by its disagree port to Human review."""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import traceback
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from usecase_harness import (
    AGENTS_DIR,
    AGENTS_PORT,
    LOG_DIR,
    _env,  # pyright: ignore[reportPrivateUsage]
    agents,
    check,
    fake_openai,
    finish,
    kb,
    models,
    pg_url,
    put_in_files,
    service_headers,
)

OPS = {"X-Team-Id": "team_ops"}
MAYA = {**OPS, "X-Dev-User": "m.okafor@harborpine.example"}
NADIA = {"X-Team-Id": "team_security", "X-Dev-User": "n.petrov@harborpine.example"}
MODELS_ADMIN = service_headers("models")
RUN = uuid.uuid4().hex[:6]
SETTLED = {"succeeded", "failed", "cancelled"}
SEED = AGENTS_DIR / "seed" / "engine_workflows.json"

# What page 1 of the scan says, and what the fake model answers from it.
MARK = "UC568-LEVY-0042"
PAGE_ONE = [
    "NOTICE OF LEVY",
    f"Notice number: {MARK}",
    "Taxpayer: Jordan Avery",
    "Amount due: 1284.50",
    "Issue date: 2026-03-14",
]
TABLE = [["Account", "Balance", "Status"], ["CHK-0091", "1284.50", "Held"], ["SAV-0217", "310.00", "Open"]]
PROPOSED = [
    {"key": "notice_no", "label": "Notice number", "type": "text", "description": "The notice's number"},
    {"key": "taxpayer", "label": "Taxpayer", "type": "text", "description": "Who owes the tax"},
    {"key": "amount_due", "label": "Amount due", "type": "money", "description": "What is owed"},
    {"key": "issue_date", "label": "Issue date", "type": "date", "description": "When the notice was issued"},
]
VALUES = {
    "notice_no": {"value": MARK, "quote": MARK, "page": 1},
    "taxpayer": {"value": "Jordan Avery", "quote": "Jordan Avery", "page": 1},
    "amount_due": {"value": 1284.5, "quote": "1284.50", "page": 1},
    "issue_date": {"value": "2026-03-14", "quote": "2026-03-14", "page": 1},
}
RENAMED = {("debtor_name" if k == "taxpayer" else k): v for k, v in VALUES.items()}
# The propose call must see pages 1 to 5 only: the rule does not match a prompt that carries page 6's footer.
RULES = {
    "rules": [
        {"when": rf"^Fields:.*debtor_name.*{MARK}", "tool": "final_result", "arguments": RENAMED},
        {"when": rf"^Fields:.*{MARK}", "tool": "final_result", "arguments": VALUES},
        {
            "when": rf"^(The person reading it says it is[^\n]*\s*)?Document:(?!.*Page 6 of 12).*{MARK}",
            "tool": "final_result",
            "arguments": {"name": "Tax levy notice", "fields": PROPOSED},
        },
    ]
}


# ---- the 12-page scan ----


def _page_image(number: int) -> Image.Image:
    """One scanned page at 150 dpi: text drawn into pixels, so the PDF has no text layer and is read by OCR."""
    img = Image.new("L", (1275, 1650), 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=34)
    y = 120
    lines = PAGE_ONE if number == 1 else [f"Schedule section {number}", "Payments are applied in the order received."]
    for line in lines:
        draw.text((110, y), line, fill=0, font=font)
        y += 70
    if number == 3:
        # A ruled table, read row by row.
        top, left, w, h = y + 40, 110, 340, 90
        for r, row in enumerate(TABLE):
            y0 = top + r * h
            draw.line([left, y0, left + 3 * w, y0], fill=0, width=2)
            for c, cell in enumerate(row):
                draw.text((left + c * w + 24, y0 + 26), cell, fill=0, font=font)
        draw.line([left, top + 3 * h, left + 3 * w, top + 3 * h], fill=0, width=2)
    if number == 2:
        # A faded, smudged word, as on a worn photocopy: OCR reads it with low confidence, if at all.
        faded = Image.new("L", (400, 80), 255)
        ImageDraw.Draw(faded).text((10, 10), "Reference", fill=185, font=ImageFont.load_default(size=30))
        img.paste(faded.filter(ImageFilter.GaussianBlur(1.6)), (110, 400))
    draw.text((110, 1520), f"Page {number} of 12", fill=0, font=font)
    return img


def scan_pdf() -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    for n in range(1, 13):
        c.drawImage(ImageReader(_page_image(n)), 0, 0, width=LETTER[0], height=LETTER[1])
        c.showPage()
    c.save()
    return buf.getvalue()


def text_pdf(line: str) -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    c.drawString(72, 700, line)
    c.save()
    return buf.getvalue()


# ---- helpers ----


def body(res: httpx.Response) -> dict[str, Any]:
    try:
        got = res.json()
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def got(res: httpx.Response) -> Any:
    return body(res).get("data")


def code(res: httpx.Response) -> str | None:
    error = body(res).get("error")
    return str(error.get("code")) if isinstance(error, dict) else None


def said(res: httpx.Response) -> str:
    return f"{res.request.method} {res.request.url.path} answered {res.status_code}: {res.text[:200]}"


def until(what: Callable[[], Any], timeout: float = 90) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found := what():
            return found
        time.sleep(0.5)
    return None


def story(name: str, steps: Callable[[], None]) -> None:
    """One story's steps; an exception is that story's FAIL line, so the next story still runs and says its own."""
    try:
        steps()
    except Exception as e:
        check(name, False, f"{type(e).__name__}: {e} | {traceback.format_exc(limit=2)[-300:]}")


@contextmanager
def worker(files_url: str, models_url: str, documents_url: str) -> Generator[None]:
    env = _env() | {
        "OPS_DATABASE_URL": pg_url(),
        "OPS_MODELS_URL": models_url,
        "OPS_MODELS_KEY": "mk_dev_agents",
        "OPS_FILES_URL": files_url,
        "OPS_DOCUMENTS_URL": documents_url,
        "OPS_ENGINE_POLL_SECONDS": "0.2",
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "worker-uc568.log").open("ab") as fh:
        proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "ops_agents.api.worker"], cwd=AGENTS_DIR, env=env, stdout=fh, stderr=fh
        )
    try:
        yield
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def read(documents: httpx.Client, fid: str, extra: dict[str, Any]) -> tuple[httpx.Response, dict[str, Any]]:
    """A read, followed until it is done when documents-service answers it in the background."""
    res = documents.post("/v1/documents/extractions", json={"fileId": fid, **extra})
    row = got(res) or {}
    if row.get("id") and row.get("status") in ("queued", "running"):
        row = until(lambda: _settled(documents, str(row["id"])), 240) or row
    return res, row


def _settled(documents: httpx.Client, eid: str) -> dict[str, Any] | None:
    row = got(documents.get(f"/v1/documents/extractions/{eid}")) or {}
    return row if row.get("status") not in ("queued", "running") else None


def model_calls(model_admin: httpx.Client, run_id: str) -> list[dict[str, Any]]:
    items = (got(model_admin.get("/v1/models/calls", params={"pageSize": 200}, headers=MODELS_ADMIN)) or {}).get(
        "items"
    ) or []
    return [c for c in items if c.get("runId") == run_id]


def publish(api: httpx.Client, definition: dict[str, Any]) -> str:
    saved = api.post("/v1/workflows/definitions", json={"definition": definition}, headers=OPS)
    if saved.status_code not in (200, 201):
        return said(saved)
    asked = api.post(f"/v1/workflows/definitions/{definition['id']}/publish-requests", json={}, headers=OPS)
    return str((got(asked) or {}).get("status") or said(asked))


def runs_of(api: httpx.Client, wid: str) -> list[dict[str, Any]]:
    """Every run of the workflow, a page of 100 (the most the list gives) at a time."""
    out: list[dict[str, Any]] = []
    for number in range(1, 11):
        params: dict[str, Any] = {"workflowId": wid, "pageSize": 100, "page": number}
        rows = (got(api.get("/v1/runs", params=params, headers=OPS)) or {}).get("data") or []
        out += rows
        if len(rows) < 100:
            break
    return out


def end(nid: str, outcome: str, *, failed: bool = False) -> dict[str, Any]:
    params: dict[str, Any] = {"outcome": outcome, **({"result": "failed"} if failed else {})}
    return {"id": nid, "type": "ops.flow.end", "typeVersion": 1, "name": outcome.title(), "parameters": params}


def request(schema: dict[str, Any] | None) -> dict[str, Any]:
    node: dict[str, Any] = {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "name": "Request"}
    if schema is not None:
        node["parameters"] = {"inputSchema": schema}
    return node


FILE_INPUT = {"type": "object", "required": ["fileId"], "properties": {"fileId": {"type": "string", "format": "file"}}}
FORM_SCHEMA = {
    "type": "object",
    "title": "Request a statement",
    "required": ["customerId"],
    "properties": {
        "customerId": {"type": "string", "title": "Customer number"},
        "reason": {"type": "string", "title": "Why you need it"},
        "document": {"type": "string", "format": "file", "title": "Proof of identity"},
    },
}


def straight(wid: str, schema: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "id": wid,
        "name": wid,
        "nodes": [request(schema), end("done", "received")],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }


# Each row's run ends failed when its status column says bad, so a batch has failed rows to retry.
BATCH_SCHEMA = {
    "type": "object",
    "required": ["customerId", "status"],
    "properties": {"customerId": {"type": "string"}, "status": {"type": "string"}},
}


def batch_flow(wid: str) -> dict[str, Any]:
    gate = {
        "id": "gate",
        "type": "ops.flow.if",
        "typeVersion": 1,
        "name": "Marked bad?",
        "parameters": {"conditions": [{"left": "$.input.status", "op": "eq", "right": "bad"}]},
    }
    return {
        "schemaVersion": 2,
        "id": wid,
        "name": wid,
        "nodes": [request(BATCH_SCHEMA), gate, end("done", "checked"), end("bad", "rejected", failed=True)],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "gate", "port": "in"}},
            {"from": {"node": "gate", "port": "false"}, "to": {"node": "done", "port": "in"}},
            {"from": {"node": "gate", "port": "true"}, "to": {"node": "bad", "port": "in"}},
        ],
    }


def merge_flow(wid: str) -> dict[str, Any]:
    combine = {
        "id": "combine",
        "type": "ops.data.combine",
        "typeVersion": 1,
        "name": "Combine facts",
        "parameters": {
            "sources": [
                {"name": "notice", "values": {"amount": "$.input.noticeAmount", "account": "$.input.account"}},
                {"name": "bank", "values": {"amount": "$.input.bankAmount", "account": "$.input.account"}},
            ],
            "fields": [{"field": "amount", "type": "money"}],
            "onDisagreement": "port",
        },
    }
    review = {
        "id": "review",
        "type": "ops.flow.humanReview",
        "typeVersion": 1,
        "name": "Check the disagreement",
        "parameters": {"title": "Check the disagreement"},
    }
    return {
        "schemaVersion": 2,
        "id": wid,
        "name": wid,
        "nodes": [
            request(None),
            combine,
            review,
            end("matched", "matched"),
            end("checked", "checked"),
            end("rejected", "rejected"),
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "combine", "port": "in"}},
            {"from": {"node": "combine", "port": "out"}, "to": {"node": "matched", "port": "in"}},
            {"from": {"node": "combine", "port": "disagree"}, "to": {"node": "review", "port": "in"}},
            {"from": {"node": "review", "port": "approve"}, "to": {"node": "checked", "port": "in"}},
            {"from": {"node": "review", "port": "reject"}, "to": {"node": "rejected", "port": "in"}},
        ],
    }


def csv_bytes(header: list[str], rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode()


# ---- the stories ----


def reads(
    documents: httpx.Client, files: httpx.Client, api: httpx.Client, model_admin: httpx.Client, scan: str
) -> None:
    # 1. The whole scan as text: every page in order, its tables, no document type.
    res, full = read(documents, scan, {"read": "text", "ocr": True})
    pages = full.get("pages") if isinstance(full.get("pages"), list) else []
    numbers = [p.get("number") for p in pages]
    text = str(full.get("text") or "")
    order = [text.find(f"Page {n} of 12") for n in range(1, 13)]
    table_page = next((p for p in pages if p.get("number") == 3), {})
    t3 = str(table_page.get("text") or "")
    check(
        "1 a 12-page scan read as full text comes back page by page in reading order, each page with its tables",
        full.get("status") == "done"
        and numbers == list(range(1, 13))
        and all(isinstance(p.get("tables"), list) and p.get("text") for p in pages)
        and all(i >= 0 for i in order)
        and order == sorted(order)
        and 0 <= t3.find("CHK-0091") < t3.find("SAV-0217"),
        {"http": said(res) if res.status_code >= 300 else res.status_code, "status": full.get("status"),
         "error": full.get("error"), "numbers": numbers, "order": order, "page3": t3[:200]},
    )  # fmt: skip

    # 2. The same read made no model call.
    calls = model_calls(model_admin, str(full.get("id")))
    check(
        "2 the full-text read makes no model call and charges nothing",
        bool(full.get("id")) and full.get("status") == "done" and calls == [] and full.get("path") is None,
        {"id": full.get("id"), "status": full.get("status"), "calls": len(calls), "path": full.get("path")},
    )

    # 3. maxPages reads only the pages asked for; an unknown read is refused.
    _, three = read(documents, scan, {"read": "text", "ocr": True, "maxPages": 3})
    shown = [p.get("number") for p in three.get("pages") or [] if isinstance(p, dict)]
    bad = documents.post("/v1/documents/extractions", json={"fileId": scan, "read": "nonsense"})
    check(
        "3 maxPages 3 reads pages 1 to 3 only, and an unknown read is refused validation_failed",
        three.get("status") == "done" and shown == [1, 2, 3] and three.get("readPages") == 3
        and bad.status_code == 400 and code(bad) == "validation_failed",
        {"pages": shown, "readPages": three.get("readPages"), "bad": said(bad)},
    )  # fmt: skip

    # 4. An Extract from file step reads Full text with no fields: it validates clean, and its run returns only the
    # pages asked for. (A Files read request reads fields or proposes them; the file page shows the full text from
    # the file's layout, so a request carries no text read.)
    step = {
        "id": "read",
        "type": "ops.ai.extract",
        "typeVersion": 1,
        "name": "Read the notice",
        "parameters": {"file": "$.input.fileId", "read": "text", "ocr": True, "maxPages": 2},
    }
    text_wid = f"uc568_text_{RUN}"
    wf = {
        "schemaVersion": 2,
        "id": text_wid,
        "name": "Read a notice as text",
        "nodes": [request(FILE_INPUT), step, *(end(p, p) for p in ("ok", "review", "unreadable", "error"))],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "read", "port": "in"}}]
        + [
            {"from": {"node": "read", "port": p}, "to": {"node": p, "port": "in"}}
            for p in ("ok", "review", "unreadable", "error")
        ],
    }
    valid = got(api.post("/v1/workflows/definitions/validate", json={"definition": wf}, headers=OPS)) or {}
    live = publish(api, wf)
    body_ = {"workflowId": text_wid, "mode": "live", "input": {"fileId": scan}}
    run_id = str((got(api.post("/v1/runs", json=body_, headers=OPS)) or {}).get("runId"))

    def ended() -> dict[str, Any] | None:
        run = got(api.get(f"/v1/runs/{run_id}", headers=OPS)) or {}
        return run if run.get("status") in SETTLED else None

    run = (until(ended, 240) if live == "approved" else None) or {}
    blob = json.dumps(run)
    check(
        "4 an Extract from file step reading Full text of 2 pages validates clean, and its run returns those two "
        "pages' text",
        valid.get("ok") is True and run.get("status") == "succeeded" and run.get("outcome") == "ok"
        and "Page 2 of 12" in blob and "Page 3 of 12" not in blob,
        {"checks": [f"{c.get('level')}: {c.get('message')}" for c in valid.get("checks") or []], "publish": live,
         "run": run.get("status"), "outcome": run.get("outcome"), "error": run.get("error")},
    )  # fmt: skip


def proposed(documents: httpx.Client, scan: str) -> None:
    # 5. The model proposes the fields from the first 5 pages, and the file is read with them.
    res, prop = read(documents, scan, {"read": "propose", "ocr": True, "hint": "a tax levy notice"})
    proposal = prop.get("proposal") or {}
    keys = [f.get("key") for f in proposal.get("fields") or []]
    fields = prop.get("fields") or {}
    grounded = {
        k: bool((f.get("citation") or {}).get("quote")) and (f.get("citation") or {}).get("page") == 1
        and isinstance(f.get("confidence"), (int, float))
        for k, f in fields.items()
    }  # fmt: skip
    check(
        "5 the model proposes fields from the first 5 pages, and every value read carries its quote, page and "
        "a confidence from the checks",
        prop.get("status") == "done" and keys == [f["key"] for f in PROPOSED] and set(grounded) == set(keys)
        and all(grounded.values()) and (fields.get("notice_no") or {}).get("value") == MARK,
        {"http": res.status_code, "status": prop.get("status"), "error": prop.get("error"), "proposal": proposal,
         "grounded": grounded},
    )  # fmt: skip

    # 6. Rename a field and save the proposal as the team's document type, the file its first sample; reading again
    # with that type gives the same values.
    renamed = [
        {**f, "key": "debtor_name", "label": "Debtor name"} if f["key"] == "taxpayer" else f
        for f in (proposal.get("fields") or PROPOSED)
    ]
    type_id = f"uc568_levy_{RUN}"
    saved = documents.post(
        "/v1/document-types",
        json={"id": type_id, "name": "Tax levy notice (uc-568)", "fields": renamed, "sampleFileId": scan},
    )
    held = got(documents.get(f"/v1/document-types/{type_id}")) or {}
    samples = [s.get("fileId") for s in held.get("samples") or []]
    listed = got(documents.get("/v1/document-types", headers=NADIA)) or {}
    elsewhere = [t.get("id") for t in listed.get("items") or []]
    _, again = read(documents, scan, {"documentTypeId": type_id, "ocr": True})
    values = {k: (v or {}).get("value") for k, v in (again.get("fields") or {}).items()}
    want = {k: v["value"] for k, v in RENAMED.items()}
    check(
        "6 Save as document type creates the team's type with the file as its first sample, and reading the file "
        "with it gives the same fields",
        saved.status_code == 201 and samples == [scan] and type_id not in elsewhere and values == want,
        {"saved": said(saved), "samples": samples, "other team sees it": type_id in elsewhere, "values": values},
    )

    # 7. A read that reaches maxTokens stops with what it read and says so.
    _, short = read(documents, scan, {"read": "propose", "ocr": True, "maxTokens": 120})
    check(
        "7 a proposed read that reaches maxTokens stops with partial results and says so",
        short.get("status") == "done" and short.get("partial") is True and 0 < int(short.get("readPages") or 0) < 12,
        {"status": short.get("status"), "partial": short.get("partial"), "readPages": short.get("readPages"),
         "error": short.get("error")},
    )  # fmt: skip


def submit(
    api: httpx.Client, slug: str, token: str | None, values: dict[str, Any], *, address: str, pdf: bytes | None = None
) -> httpx.Response:
    params = {"t": token} if token is not None else {}
    sent = dict(values)
    if pdf is not None:
        # A file field's value is the id Files gave the upload, as the embed page sends it.
        up = api.post(
            f"/v1/forms/public/{slug}/files",
            params={**params, "name": "proof.pdf"},
            content=pdf,
            headers={"Content-Type": "application/pdf", "X-Forwarded-For": address},
        )
        sent["document"] = (got(up) or {}).get("fileId")
    return api.post(
        f"/v1/forms/public/{slug}/submit", params=params, json={"values": sent}, headers={"X-Forwarded-For": address}
    )


def forms(api: httpx.Client) -> None:
    wid, bare = f"uc568_form_{RUN}", f"uc568_bare_{RUN}"
    live = {publish(api, straight(wid, FORM_SCHEMA)), publish(api, straight(bare, None))}
    check("setup the form workflows go live", live == {"approved"}, live)

    # 8. Share as a form: a signed link that expires on the chosen day; a trigger with no input form cannot be shared.
    share = {"mode": "link", "expiresInDays": 30, "dailyCap": 50, "title": "Request a statement",
             "description": "We post it within two days.", "afterText": "Thanks, we have your request."}  # fmt: skip
    made = api.post(f"/v1/workflows/{wid}/forms", json=share, headers=OPS)
    form = got(made) or {}
    none = api.post(f"/v1/workflows/{bare}/forms", json=share, headers=OPS)
    slug, token = str(form.get("slug")), str(form.get("token"))
    public = api.get(f"/v1/forms/public/{slug}", params={"t": token})
    shown = got(public) or {}
    days = 0.0
    if form.get("expiresAt"):
        from datetime import UTC, datetime  # noqa: PLC0415

        days = (datetime.fromisoformat(str(form["expiresAt"]).replace("Z", "+00:00")) - datetime.now(UTC)).days
    check(
        "8 a builder shares a workflow as a form and gets a signed link that expires in 30 days; a person with the "
        "link sees only its title, description and fields; a trigger with no input form cannot be shared",
        made.status_code == 201 and all(form.get(k) for k in ("id", "slug", "token", "url")) and 29 <= days <= 30
        and public.status_code == 200 and set(shown) == {"title", "description", "form", "afterText"}
        and none.status_code == 409 and code(none) == "form_needs_inputs",
        {"made": said(made), "days": days, "public": said(public), "keys": sorted(shown), "bare": said(none)},
    )  # fmt: skip

    # 9. A submission with a file starts a run in the form's team, created by the form and named by its title.
    sent = submit(api, slug, token, {"customerId": "CUS-1001", "reason": "Mortgage"}, address="198.51.100.1",
                  pdf=text_pdf("Passport scan"))  # fmt: skip
    # The public answer says only that it was received; the builder finds the run the form started in the runs list.
    by_form = [r for r in runs_of(api, wid) if r.get("createdBy") == f"trigger:form:{form.get('id')}"]
    run = got(api.get(f"/v1/runs/{by_form[0].get('id')}", headers=OPS)) or {} if by_form else {}
    check(
        "9 a submitted form starts a run in the form's team, started by the hosted form under its title, with the "
        "attached file",
        sent.status_code in (201, 202) and run.get("createdBy") == f"trigger:form:{form.get('id')}"
        and (run.get("startedBy") or {}).get("name") == "Request a statement"
        and bool((run.get("input") or {}).get("document")),
        {"sent": said(sent), "createdBy": run.get("createdBy"), "startedBy": run.get("startedBy"),
         "input": run.get("input")},
    )  # fmt: skip

    # 10. Rotate: the old link is refused, as is no token and another form's token; the new one works.
    other = got(api.post(f"/v1/workflows/{wid}/forms", json={**share, "title": "Another"}, headers=OPS)) or {}
    before = len(runs_of(api, wid))
    rotated = api.post(f"/v1/forms/{form.get('id')}/rotate", headers=OPS)
    fresh = str((got(rotated) or {}).get("token"))
    old = submit(api, slug, token, {"customerId": "CUS-1002"}, address="198.51.100.2")
    bare_try = submit(api, slug, None, {"customerId": "CUS-1002"}, address="198.51.100.3")
    crossed = submit(api, slug, str(other.get("token")), {"customerId": "CUS-1002"}, address="198.51.100.4")
    refused_runs = len(runs_of(api, wid)) - before
    new = submit(api, slug, fresh, {"customerId": "CUS-1002"}, address="198.51.100.5")
    check(
        "10 a rotated link, no token or another form's token is refused and starts nothing, and the new link works",
        rotated.status_code == 200 and old.status_code == 401 and code(old) == "form_link_expired"
        and bare_try.status_code == 401 and crossed.status_code in (401, 404) and refused_runs == 0
        and new.status_code in (201, 202),
        {"rotate": said(rotated), "old": said(old), "none": said(bare_try), "crossed": said(crossed),
         "runs from refusals": refused_runs, "new": said(new)},
    )  # fmt: skip

    # 11. A members-only form: a member of the team submits as themselves; anyone else is refused.
    members = got(api.post(f"/v1/workflows/{wid}/forms", json={**share, "mode": "members"}, headers=OPS)) or {}
    mslug = str(members.get("slug"))
    opened = api.get(f"/v1/forms/{mslug}/members", headers=MAYA)
    parts = {"values": {"customerId": "CUS-1003"}}
    mine = api.post(f"/v1/forms/{mslug}/members", json=parts, headers=MAYA)
    member_run = got(api.get(f"/v1/runs/{(got(mine) or {}).get('runId')}", headers=OPS)) or {}
    via = ((member_run.get("startedBy") or {}).get("via") or {}).get("id")
    outsider = api.post(f"/v1/forms/{mslug}/members", json=parts, headers=NADIA)
    check(
        "11 a members-only form starts the run as the member who sent it, and a person outside the team is refused",
        opened.status_code == 200 and mine.status_code in (201, 202) and via == "hosted_form"
        and not str(member_run.get("createdBy")).startswith("trigger:")
        and outsider.status_code == 403 and code(outsider) == "form_members_only",
        {"open": said(opened), "sent": said(mine), "createdBy": member_run.get("createdBy"), "via": via,
         "outsider": said(outsider)},
    )  # fmt: skip

    # 12. The rate per address and the daily cap refuse with why, start nothing, and show in Activity.
    flood = got(api.post(f"/v1/workflows/{wid}/forms", json={**share, "title": f"Flood {RUN}"}, headers=OPS)) or {}
    capped = (
        got(
            api.post(f"/v1/workflows/{wid}/forms", json={**share, "title": f"Capped {RUN}", "dailyCap": 2}, headers=OPS)
        )
        or {}
    )
    before = len(runs_of(api, wid))
    one = [submit(api, str(flood.get("slug")), str(flood.get("token")), {"customerId": f"CUS-2{i:03}"},
                  address="203.0.113.7").status_code for i in range(10)]  # fmt: skip
    eleventh = submit(api, str(flood.get("slug")), str(flood.get("token")), {"customerId": "CUS-2999"},
                      address="203.0.113.7")  # fmt: skip
    second = submit(api, str(flood.get("slug")), str(flood.get("token")), {"customerId": "CUS-3000"},
                    address="203.0.113.8")  # fmt: skip
    day = [submit(api, str(capped.get("slug")), str(capped.get("token")), {"customerId": f"CUS-4{i:03}"},
                  address=f"192.0.2.{10 + i}") for i in range(3)]  # fmt: skip
    started = len(runs_of(api, wid)) - before
    rows = (got(api.get("/v1/activity", params={"pageSize": 100}, headers=OPS)) or {}).get("data") or []

    def refusals(form_row: dict[str, Any], outcome: str) -> list[dict[str, Any]]:
        mark = (str(form_row.get("id")), str(form_row.get("slug")))
        return [r for r in rows if any(m in json.dumps(r) for m in mark) and r.get("outcome") == outcome]

    shown_flood, shown_cap = refusals(flood, "rate_limited"), refusals(capped, "daily_cap")
    check(
        "12 the 11th submission in a minute from one address is refused while another address passes, a third "
        "submission on a cap of 2 is refused, none starts a run, and Activity shows each refusal with its reason",
        all(s in (201, 202) for s in one) and eleventh.status_code == 429 and code(eleventh) == "form_rate_limited"
        and second.status_code in (201, 202)
        and [d.status_code for d in day[:2]] in ([201, 201], [202, 202]) and day[2].status_code == 429
        and code(day[2]) == "daily_cap" and started == 13
        and bool(shown_flood) and bool(shown_cap) and all(r.get("detail") for r in shown_flood + shown_cap),
        {"first ten": one, "11th": said(eleventh), "second address": second.status_code,
         "cap": [said(d) for d in day], "runs started": started,
         "activity": [(r.get("outcome"), r.get("detail")) for r in shown_flood + shown_cap][:6]},
    )  # fmt: skip


def batches(api: httpx.Client, files_url: str) -> None:
    wid = f"uc568_batch_{RUN}"
    check("setup the batch workflow goes live", publish(api, batch_flow(wid)) == "approved", wid)
    bad_rows = {17, 88, 151}
    rows = [[f"CUS-{5000 + i}", "bad" if i in bad_rows else "ok", f"note {i}"] for i in range(1, 201)]

    def upload(name: str, data_: bytes) -> str:
        return put_in_files(files_url, name, data_, mime="text/csv", headers=OPS)

    good = upload("customers.csv", csv_bytes(["customerId", "status", "notes"], rows))

    # 13. A dry run counts the rows, maps the header to the inputs and shows the first 5, starting nothing.
    dry = api.post(f"/v1/workflows/{wid}/batches", json={"fileId": good, "mode": "live", "dryRun": True}, headers=OPS)
    plan = got(dry) or {}
    mapping = json.dumps(plan.get("mapping"))
    check(
        "13 a dry run of a 200-row CSV shows the row count, the columns mapped to the workflow's inputs, the "
        "column ignored and the first 5 rows, and starts nothing",
        dry.status_code == 200 and plan.get("rows") == 200 and "customerId" in mapping and "status" in mapping
        and "notes" in json.dumps(plan.get("ignored")) and len(plan.get("sample") or []) == 5
        and runs_of(api, wid) == [],
        {"dry": said(dry), "runs": len(runs_of(api, wid))},
    )  # fmt: skip

    # 14. Too many rows, or a header naming none of the inputs, is refused before any run starts.
    big = upload("too-many.csv", csv_bytes(["customerId", "status"], [[f"CUS-{i}", "ok"] for i in range(501)]))
    odd = upload("wrong-header.csv", csv_bytes(["name", "email"], [["Ann", "ann@example.com"]]))
    over = api.post(f"/v1/workflows/{wid}/batches", json={"fileId": big, "mode": "live", "dryRun": False}, headers=OPS)
    unmatched = api.post(
        f"/v1/workflows/{wid}/batches", json={"fileId": odd, "mode": "live", "dryRun": False}, headers=OPS
    )
    check(
        "14 a 501-row file and a file whose header names none of the inputs are refused with the count or the "
        "columns named, and no run starts",
        over.status_code == 422 and code(over) == "batch_too_many_rows" and "501" in over.text
        and unmatched.status_code == 422 and code(unmatched) == "batch_no_matching_columns" and "name" in unmatched.text
        and runs_of(api, wid) == [],
        {"over": said(over), "unmatched": said(unmatched), "runs": len(runs_of(api, wid))},
    )  # fmt: skip

    # 15. The batch runs one run per row; its page counts them and lists failed rows first, each with its run.
    started = api.post(f"/v1/workflows/{wid}/batches", json={"fileId": good, "mode": "live", "dryRun": False},
                       headers=OPS)  # fmt: skip
    bid = str((got(started) or {}).get("id"))

    def settled() -> dict[str, Any] | None:
        b = got(api.get(f"/v1/batches/{bid}", headers=OPS)) or {}
        done = int(b.get("finished") or 0) + int(b.get("failed") or 0)
        return b if b.get("total") and done == b["total"] and not b.get("running") else None

    batch = (
        (until(settled, 300) if started.status_code == 202 else None)
        or got(api.get(f"/v1/batches/{bid}", headers=OPS))
        or {}
    )
    listed = batch.get("rows") or []
    check(
        "15 the batch starts one run per row and reads 197 of 200 finished, 3 failed, failed rows first, each with "
        "its run",
        started.status_code == 202 and (batch.get("total"), batch.get("finished"), batch.get("failed")) == (200, 197, 3)
        and [r.get("status") for r in listed[:3]] == ["failed"] * 3 and all(r.get("runId") for r in listed)
        and len(runs_of(api, wid)) == 200,
        {"start": said(started), "counts": {k: batch.get(k) for k in ("total", "finished", "failed", "running")},
         "first": [r.get("status") for r in listed[:4]]},
    )  # fmt: skip

    # 16. Retry failed rows starts only the failed ones; the CSV download is the same table.
    retried = api.post(f"/v1/batches/{bid}/retry", headers=OPS)
    again = (until(settled, 120) if retried.status_code in (200, 202) else None) or {}
    after = runs_of(api, wid)
    ok_runs = [r for r in again.get("rows") or [] if r.get("status") == "succeeded"]
    table = api.get(f"/v1/batches/{bid}/results.csv", headers=OPS)
    lines = list(csv.DictReader(io.StringIO(table.text))) if table.status_code == 200 else []
    failed_lines = [r for r in lines if "fail" in json.dumps(r).lower()]
    check(
        "16 Retry failed rows starts a new run for the 3 failed rows only, and Download as CSV gives the same table",
        retried.status_code in (200, 202) and len(after) == 203 and len(ok_runs) == 197
        and again.get("failed") == 3 and len(lines) == 200 and len(failed_lines) == 3,
        {"retry": said(retried), "runs": len(after), "ok runs": len(ok_runs), "csv": said(table) if not lines else
         len(lines), "failed in csv": len(failed_lines)},
    )  # fmt: skip


def merge(api: httpx.Client) -> None:
    # 17. The two_source_match seed validates, and a run whose sources disagree leaves Combine facts by disagree.
    seeds = json.loads(SEED.read_text())
    seed = next((w for w in seeds if w.get("id") == "two_source_match"), None)
    # The seed loader stores a seed without its teamId (the team it belongs to), so that is what is validated.
    stored = {k: v for k, v in (seed or {}).items() if k != "teamId"}
    valid = got(api.post("/v1/workflows/definitions/validate", json={"definition": stored}, headers=OPS)) or {}
    types = [n.get("type") for n in (seed or {}).get("nodes") or []]
    wid = f"uc568_merge_{RUN}"
    live = publish(api, merge_flow(wid))
    body_ = {"workflowId": wid, "mode": "live", "runKey": f"uc568-{uuid.uuid4().hex[:8]}",
             "input": {"noticeAmount": "1284.50", "bankAmount": "1248.50", "account": "CHK-0091"}}  # fmt: skip
    run_id = str((got(api.post("/v1/runs", json=body_, headers=OPS)) or {}).get("runId"))

    def waiting() -> dict[str, Any] | None:
        r = got(api.get(f"/v1/runs/{run_id}", headers=OPS)) or {}
        return r if r.get("status") in {"waiting", *SETTLED} else None

    run = (until(waiting, 90) if live == "approved" else None) or {}
    combine = next((s for s in run.get("steps") or [] if s.get("nodeId") == "combine"), {})
    conflicts = [c.get("field") for c in (combine.get("output") or {}).get("conflicts") or []]
    check(
        "17 the two_source_match example validates clean (Join, then Combine facts), and a run whose sources "
        "disagree leaves by the disagree port and waits at Human review with the disagreement",
        seed is not None and valid.get("ok") is True and "ops.flow.join" in types and "ops.data.combine" in types
        and live == "approved" and run.get("status") == "waiting" and combine.get("port") == "disagree"
        and conflicts == ["amount"],
        {"seed": seed is not None, "valid": valid.get("ok"),
         "checks": [c.get("message") for c in valid.get("checks") or []], "publish": live, "status": run.get("status"),
         "port": combine.get("port"), "conflicts": conflicts},
    )  # fmt: skip


def wanted(name: str) -> bool:
    """UC568_STORIES=S1,S3 runs only those stories (a card's verify proves one acceptance line each); all by default."""
    picked = {s.strip() for s in os.environ.get("UC568_STORIES", "").split(",") if s.strip()}
    return not picked or name in picked


def main() -> None:
    agents_url = f"http://127.0.0.1:{AGENTS_PORT}"
    rules = Path(tempfile.mkdtemp(prefix="uc568-model-"))
    try:
        (rules / "script.json").write_text(json.dumps(RULES))
        with (
            tempfile.TemporaryDirectory(prefix="uc568-") as tmp,
            fake_openai(rules) as fake,
            models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
            kb(Path(tmp) / "files", models_url=models_url, document_types=True, agents_url=agents_url) as knowledge,
            agents(
                kb_url=str(knowledge.base_url).rstrip("/"),
                models_url=models_url,
                models_key="mk_dev_agents",
                env={"OPS_FILES_URL": knowledge.files_url, "OPS_DOCUMENTS_URL": knowledge.documents_url},
            ) as api,
            worker(knowledge.files_url, models_url, knowledge.documents_url),
            httpx.Client(base_url=models_url, timeout=30) as model_admin,
            httpx.Client(base_url=knowledge.files_url, headers=OPS, timeout=60) as files,
            httpx.Client(base_url=knowledge.documents_url, headers=OPS, timeout=300) as documents,
        ):
            scan = put_in_files(knowledge.files_url, "levy-scan.pdf", scan_pdf(), headers=OPS)
            if wanted("S1"):
                story("1 the scan is read as full text", lambda: reads(documents, files, api, model_admin, scan))
            if wanted("S2"):
                story("5 the fields are proposed and saved", lambda: proposed(documents, scan))
            if wanted("S3"):
                story("8 the workflow is shared as a form", lambda: forms(api))
            if wanted("S4"):
                story("13 the workflow runs once per row of a CSV", lambda: batches(api, knowledge.files_url))
            if wanted("S5"):
                story("17 the two sources are merged", lambda: merge(api))
    finally:
        shutil.rmtree(rules, ignore_errors=True)
    finish()


if __name__ == "__main__":
    main()
