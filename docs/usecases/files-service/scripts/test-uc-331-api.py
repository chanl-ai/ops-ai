# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-331 A file is read with Detect from the Files page, api layer:
docs/usecases/files-service/a-file-is-read-with-detect.md.

Own services, no real model: models-service on the fake OpenAI with an answer per documents fixture
(services/documents-service/tests/fixtures/fake-model, which also answers that a canteen menu is none of the team's
types), files-service with scanning off delivering its events to this run's agents-service, documents-service with the
seeded document types, agents-service with its shipped system_extract workflow, and a workflow worker."""

from __future__ import annotations

import hashlib
import io
import os
import signal
import subprocess
import tempfile
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas
from usecase_harness import (
    AGENTS_DIR,
    AGENTS_PORT,
    DB,
    LOG_DIR,
    ROOT,
    _env,  # pyright: ignore[reportPrivateUsage]
    agents,
    check,
    data,
    fake_openai,
    finish,
    kb,
    models,
)

DOCS = ROOT / "services" / "documents-service"
RULES = DOCS / "tests" / "fixtures" / "fake-model"
INVOICES = DOCS / "tests" / "fixtures" / "invoice"
OPS = {"X-Team-Id": "team_ops"}
MAYA = {**OPS, "X-Dev-User": "m.okafor@northfieldbank.com"}
SETTLED = {"succeeded", "failed", "cancelled"}


@contextmanager
def worker(files_url: str, models_url: str, documents_url: str) -> Generator[None]:
    pg = os.environ.get("OPS_PG_PORT", "5477")
    env = _env() | {
        "OPS_DATABASE_URL": f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}",
        "OPS_MODELS_URL": models_url,
        "OPS_MODELS_KEY": "mk_dev_agents",
        "OPS_FILES_URL": files_url,
        "OPS_DOCUMENTS_URL": documents_url,
        "OPS_ENGINE_POLL_SECONDS": "0.2",
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "worker-uc331.log").open("ab") as fh:
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


def menu() -> bytes:
    """A page of none of the seeded types; the fake model's classify rule answers that none fits."""
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica", 12)
    for i, line in enumerate(["Staff canteen menu for the week", "Monday: lentil soup", "Tuesday: fish pie"]):
        c.drawString(72, 700 - 24 * i, line)
    c.save()
    return buf.getvalue()


def upload(files: httpx.Client, name: str, body: bytes) -> str:
    meta = {"name": name, "size": len(body), "mime": "application/pdf", "purpose": "case_attachment"}
    ticket = data(files.post("/v1/files/uploads", json={**meta, "digest": hashlib.sha256(body).hexdigest()}))
    files.put(ticket["uploadUrl"], headers=ticket.get("headers") or {}, content=body).raise_for_status()
    return str(data(files.post(f"/v1/files/uploads/{ticket['fileId']}/complete"))["file"]["id"])


def until(fn: Any, seconds: float = 90) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if (got := fn()) is not None:
            return got
        time.sleep(0.5)
    return None


def ask(files: httpx.Client, fid: str, body: dict[str, Any]) -> tuple[httpx.Response, dict[str, Any] | None]:
    """A read request and, once delivered, the request naming the run it started."""
    asked = files.post(f"/v1/files/{fid}/read-requests", json=body, headers={"Idempotency-Key": uuid.uuid4().hex})
    key = str((data(asked) or {}).get("key"))

    def started() -> dict[str, Any] | None:
        found = data(files.get(f"/v1/files/{fid}/read-requests/{key}")) or {}
        return found if found.get("runId") else None

    return asked, until(started)


def run_in(api: httpx.Client, run_id: str, states: set[str]) -> dict[str, Any] | None:
    run = data(api.get(f"/v1/runs/{run_id}", headers=OPS)) or {}
    return run if run.get("status") in states else None


def main() -> None:
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    agents_url = f"http://127.0.0.1:{AGENTS_PORT}"
    with (
        tempfile.TemporaryDirectory(prefix="uc331-") as tmp,
        fake_openai(RULES) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        kb(Path(tmp) / "files", models_url=models_url, document_types=True, agents_url=agents_url) as knowledge,
        agents(kb_url=str(knowledge.base_url).rstrip("/"), models_url=models_url, models_key="mk_dev_agents") as api,
        worker(knowledge.files_url, models_url, knowledge.documents_url),
        httpx.Client(base_url=knowledge.files_url, headers=OPS, timeout=30) as files,
    ):
        invoice = upload(files, "INVA01.pdf", (INVOICES / "INVA01.pdf").read_bytes())
        asked, followed = ask(files, invoice, {})
        run = until(lambda: run_in(api, str((followed or {}).get("runId")), SETTLED)) if followed else None
        read = (data(files.get(f"/v1/files/{invoice}")) or {}).get("data") or {}
        check(
            "1 a read request with no type is accepted with none; the run reads with Detect and saves the type found",
            asked.status_code == 202
            and (data(asked) or {}).get("documentTypeId") is None
            and (run or {}).get("outcome") == "saved"
            and (read.get("typeId"), read.get("typeName")) == ("supplier_invoice", "Supplier invoice")
            and bool(read.get("extractionId")),
            {"asked": asked.text[:300], "run": (run or {}).get("outcome"), "data": read},
        )

        unknown = upload(files, "canteen-menu.pdf", menu())
        _, followed = ask(files, unknown, {})
        run_id = str((followed or {}).get("runId"))
        waiting = until(lambda: run_in(api, run_id, {"waiting"})) if followed else None
        review = data(api.get(f"/reviews/{run_id}", headers=MAYA)) if waiting else None
        decided = api.post(f"/reviews/{run_id}/decision", json={"decision": "approved"}, headers=MAYA)
        done = until(lambda: run_in(api, run_id, SETTLED))
        saved = (data(files.get(f"/v1/files/{unknown}")) or {}).get("data") or {}
        check(
            "2 a file of none of the team's types goes to a person, and once checked is saved as not recognised",
            waiting is not None
            and review is not None
            and decided.status_code == 200
            and (done or {}).get("outcome") == "saved"
            and (saved.get("typeId"), saved.get("version")) == (None, None)
            and saved.get("typeName") is None
            and bool(saved.get("extractionId")),
            {
                "waiting": (waiting or {}).get("status"),
                "decided": decided.status_code,
                "done": (done or {}).get("outcome"),
                "data": saved,
            },
        )

        typed = upload(files, "INVA02.pdf", (INVOICES / "INVA02.pdf").read_bytes())
        asked, followed = ask(files, typed, {"documentTypeId": "supplier_invoice", "typeName": "Supplier invoice"})
        run = until(lambda: run_in(api, str((followed or {}).get("runId")), SETTLED)) if followed else None
        read = (data(files.get(f"/v1/files/{typed}")) or {}).get("data") or {}
        check(
            "3 a read request naming a type reads with it, as before",
            (data(asked) or {}).get("documentTypeId") == "supplier_invoice"
            and (run or {}).get("outcome") == "saved"
            and read.get("typeId") == "supplier_invoice",
            {"run": (run or {}).get("outcome"), "data": read},
        )
    finish()


if __name__ == "__main__":
    main()
