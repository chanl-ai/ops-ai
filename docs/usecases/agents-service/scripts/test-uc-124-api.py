"""uc-124 a workflow turns an uploaded invoice into fields a person can check, api layer:
docs/usecases/agents-service/extract-from-file.md. models-service on the fake OpenAI with this use case's rules,
files-service with scanning off, agents-service and a workflow worker that reads files through files-service. No real
model is called."""

from __future__ import annotations

import io
import signal
import subprocess
import tempfile
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from usecase_harness import (
    AGENTS_DIR,
    DB,
    LOG_DIR,
    _env,  # pyright: ignore[reportPrivateUsage]
    agents,
    bearer,
    check,
    data,
    fake_openai,
    finish,
    kb,
    models,
    pg_url,
    platform,
    signed_in,
)

RULES = AGENTS_DIR / "tests" / "fixtures" / "invoice-extraction-fake-openai"
OPS = {"X-Team-Id": "team_ops"}
FIELDS = """[{key: invoice_no, type: text, required: true}, {key: amount, type: money, required: true%s},
    {key: due_date, type: date, required: true}]"""


def pdf(pages: list[list[str]]) -> bytes:
    """A text PDF, one list of lines per page; an empty list is a page with only a drawn box, as a scan has no text."""
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=LETTER)
    for lines in pages:
        if not lines:
            c.rect(72, 400, 300, 200, fill=1)
        for i, line in enumerate(lines):
            c.drawString(72, 720 - 18 * i, line)
        c.showPage()
    c.save()
    return out.getvalue()


INVOICE = pdf([["Invoice INV-2219", "Harbor & Pine Supplies"], ["Amount due: $1,234.50", "Due 2026-11-30"]])
INVENTED = pdf([["Invoice INV-7777", "Harbor & Pine Supplies"], ["Amount due: $1,234.50", "Due 30 Nov 2026"]])
SCAN = pdf([[]])


def upload(f: httpx.Client, content: bytes, name: str) -> str:
    body = {"name": name, "size": len(content), "mime": "application/pdf", "purpose": "case_attachment"}
    ticket: dict[str, Any] = data(f.post("/v1/files/uploads", json=body, headers=OPS))
    f.put(ticket["uploadUrl"], content=content, headers={**OPS, **ticket["headers"]})
    return str(data(f.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))["file"]["id"])


def workflow(api: httpx.Client, wid: str, amount_below: float | None = None) -> None:
    extra = f", reviewBelow: {amount_below}" if amount_below is not None else ""
    yaml = f"""
schemaVersion: 2
id: {wid}
name: Invoice intake ({wid})
nodes:
  - id: start
    type: ops.trigger.request
    typeVersion: 1
    name: Request
    parameters: {{inputSchema: {{type: object, properties: {{fileId: {{type: string, format: file}}}}}}}}
  - id: extract
    type: ops.ai.extract
    typeVersion: 1
    name: Extract
    parameters: {{file: "$.input.fileId", fields: {FIELDS % extra}}}
  - {{id: ok, type: ops.flow.end, typeVersion: 1, name: OK, parameters: {{outcome: ok}}}}
  - {{id: review, type: ops.flow.end, typeVersion: 1, name: Review, parameters: {{outcome: review}}}}
  - {{id: unreadable, type: ops.flow.end, typeVersion: 1, name: Unreadable, parameters: {{outcome: unreadable}}}}
  - {{id: failed, type: ops.flow.end, typeVersion: 1, name: Failed, parameters: {{outcome: error}}}}
connections:
  - {{from: {{node: start, port: payload}}, to: {{node: extract, port: in}}}}
  - {{from: {{node: extract, port: ok}}, to: {{node: ok, port: in}}}}
  - {{from: {{node: extract, port: review}}, to: {{node: review, port: in}}}}
  - {{from: {{node: extract, port: unreadable}}, to: {{node: unreadable, port: in}}}}
  - {{from: {{node: extract, port: error}}, to: {{node: failed, port: in}}}}
"""
    saved = api.post("/v1/workflows/definitions", json={"yaml": yaml}, headers=OPS)
    if saved.status_code != 201:
        raise RuntimeError(f"setup: save {wid} answered {saved.status_code}: {saved.text[:400]}")
    live = data(api.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={}, headers=OPS))
    if live["status"] != "approved":
        raise RuntimeError(f"setup: publish {wid}: {live}")


def run(api: httpx.Client, wid: str, file_id: str) -> tuple[str | None, dict[str, Any]]:
    """The run's outcome and the extract step's output, once the worker has finished it."""
    started = data(
        api.post("/v1/runs", json={"workflowId": wid, "mode": "live", "input": {"fileId": file_id}}, headers=OPS)
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        detail = data(api.get(f"/v1/runs/{started['runId']}", headers=OPS))
        if detail["status"] in ("succeeded", "failed", "cancelled"):
            step = next((s for s in detail["steps"] if s.get("nodeId") == "extract"), {})
            return detail.get("outcome"), dict(step.get("output") or {}) | {
                "_run": detail["status"],
                "_error": detail.get("error"),
            }
        time.sleep(0.5)
    return None, {"_run": "timed out"}


@contextmanager
def worker(
    files_url: str, models_url: str, platform_url: str, documents_url: str
) -> Generator[subprocess.Popen[bytes]]:
    env = _env()
    env |= {
        "OPS_DATABASE_URL": pg_url(),
        "OPS_MODELS_URL": models_url,
        "OPS_MODELS_KEY": "mk_dev_agents",
        "OPS_FILES_URL": files_url,
        # The Extract from file step reads through documents-service (c-256).
        "OPS_DOCUMENTS_URL": documents_url,
        # The extraction floor is platform-service's extractionFloor policy (Govern > Policies).
        "OPS_PLATFORM_URL": platform_url,
        "OPS_ENGINE_POLL_SECONDS": "0.2",
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "worker-uc124.log").open("ab") as fh:
        proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "ops_agents.api.worker"], cwd=AGENTS_DIR, env=env, stdout=fh, stderr=fh
        )
    try:
        yield proc
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    with (
        tempfile.TemporaryDirectory(prefix="uc124-") as tmp,
        platform() as (people, _inner),
        fake_openai(RULES) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        # kb-service's files-service is the run's one files-service: agents() would start a second on its port.
        kb(Path(tmp), models_url=models_url, platform_url=str(people.base_url).rstrip("/")) as knowledge,
        httpx.Client(base_url=knowledge.files_url, timeout=30) as f,
        agents(models_url=models_url, models_key="mk_dev_agents", kb_url=str(knowledge.base_url).rstrip("/")) as api,
        worker(str(f.base_url).rstrip("/"), models_url, str(people.base_url).rstrip("/"), knowledge.documents_url),
    ):
        workflow(api, "uc124_invoices")
        workflow(api, "uc124_strict", amount_below=0.99)
        invoice, invented, scan = (
            upload(f, INVOICE, "invoice.pdf"),
            upload(f, INVENTED, "invented.pdf"),
            upload(f, SCAN, "scan.pdf"),
        )

        outcome, out = run(api, "uc124_invoices", invoice)
        fields = out.get("fields") or {}
        cited = (fields.get("invoice_no") or {}).get("citation")
        check(
            "1 a text invoice reads every field with a confidence and a page citation, and leaves by ok",
            outcome == "ok"
            and (fields.get("amount") or {}).get("value") == 1234.5
            and cited == {"fileId": invoice, "page": 1, "quote": "Invoice INV-2219"},
            out,
        )
        outcome, out = run(api, "uc124_invoices", invented)
        bad = (out.get("fields") or {}).get("invoice_no") or {}
        check(
            "2 a quote that is not on its page scores 0 and goes to review",
            outcome == "review" and out.get("needsReview") == ["invoice_no"] and bad.get("confidence") == 0,
            out,
        )

        outcome, out = run(api, "uc124_strict", invoice)
        check(
            "3 a field threshold above its score sends it to review",
            outcome == "review" and out.get("needsReview") == ["amount"],
            out,
        )

        # Sam, the Security admin, sets the workspace floor in Govern > Policies (platform-service).
        sam = bearer(signed_in(people, "s.adeyemi@harborpine.example"), "team_security")
        floor = people.put("/v1/policies/extractionFloor", json={"value": 0.95}, headers=sam)
        outcome, out = run(api, "uc124_invoices", invoice)
        check(
            "4 the workspace floor in Govern > Policies applies on the next run though the step sets none",
            floor.status_code == 200
            and outcome == "review"
            and out.get("floor") == 0.95
            and "amount" in out.get("needsReview", []),
            {"floor": floor.text, "out": out},
        )
        people.put("/v1/policies/extractionFloor", json={"value": 0.8}, headers=sam)

        outcome, out = run(api, "uc124_invoices", scan)
        check("5 a scan with no text and OCR off leaves by unreadable", outcome == "unreadable", out)
    finish()


if __name__ == "__main__":
    main()
