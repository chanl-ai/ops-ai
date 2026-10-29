# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-244 Extract on a file saves what was read, and deleting the file purges it, api layer:
docs/usecases/agents-service/a-file-is-extracted-and-purged.md.

Own services, no real model: models-service on the fake OpenAI with the levy notice's extraction rule, kb-service's
files-service with scanning off delivering its service events to this run's agents-service, documents-service with
the demo's document types, agents-service, and a workflow worker. The event workflows (system_extract,
extraction_corrected_save, file_deleted_purge) are the ones agents-service ships (c-250, c-252)."""

from __future__ import annotations

import hashlib
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
from usecase_harness import (
    AGENTS_DIR,
    AGENTS_PORT,
    DB,
    LOG_DIR,
    _env,  # pyright: ignore[reportPrivateUsage]
    agents,
    check,
    data,
    fake_openai,
    finish,
    kb,
    models,
    pg_url,
)

RULES = AGENTS_DIR / "tests" / "fixtures" / "levy-extraction-fake-openai"
# A comment after the PDF's end keeps it readable and makes it its own file: the seeded levy_notice samples hold the
# fixture's exact bytes, and a sample's file cannot be deleted.
NOTICE = (AGENTS_DIR / "tests" / "fixtures" / "mailbox" / "levy_notice.pdf").read_bytes() + b"\n% uc-244\n"
OPS = {"X-Team-Id": "team_ops"}
SETTLED = {"succeeded", "failed", "cancelled"}


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
    with (LOG_DIR / "worker-uc244.log").open("ab") as fh:
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


def upload(files: httpx.Client, name: str, body: bytes) -> str:
    """The console's upload (a ticket, the bytes, complete) as a case attachment of team_ops."""
    meta = {"name": name, "size": len(body), "mime": "application/pdf", "purpose": "case_attachment"}
    ticket = data(files.post("/v1/files/uploads", json={**meta, "digest": hashlib.sha256(body).hexdigest()}))
    files.put(ticket["uploadUrl"], headers=ticket.get("headers") or {}, content=body).raise_for_status()
    return str(data(files.post(f"/v1/files/uploads/{ticket['fileId']}/complete"))["file"]["id"])


def started(files: httpx.Client, fid: str, key: str) -> dict[str, Any] | None:
    found = data(files.get(f"/v1/files/{fid}/read-requests/{key}")) or {}
    return found if found.get("runId") else None


def until(fn: Any, seconds: float = 90) -> Any:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if got := fn():
            return got
        time.sleep(0.5)
    return fn()


def settled(api: httpx.Client, run_id: str) -> dict[str, Any] | None:
    d = data(api.get(f"/v1/runs/{run_id}", headers=OPS))
    return d if d and d["status"] in SETTLED else None


def purge_run(api: httpx.Client) -> dict[str, Any] | None:
    rows = data(api.get("/v1/runs", params={"workflowId": "file_deleted_purge", "pageSize": 20}, headers=OPS)) or {}
    done = [r for r in rows.get("data", []) if r["status"] in SETTLED]
    return done[0] if done else None


def corrected(files: httpx.Client, fid: str, read_at: str) -> dict[str, Any] | None:
    """The file's saved read once a newer Save data than `read_at` has written it."""
    now = (data(files.get(f"/v1/files/{fid}")) or {}).get("data") or {}
    return now if now.get("readAt") and now["readAt"] != read_at else None


def main() -> None:
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    agents_url = f"http://127.0.0.1:{AGENTS_PORT}"
    with (
        tempfile.TemporaryDirectory(prefix="uc244-") as tmp,
        fake_openai(RULES) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        kb(Path(tmp) / "files", models_url=models_url, document_types=True, agents_url=agents_url) as knowledge,
        agents(kb_url=str(knowledge.base_url).rstrip("/"), models_url=models_url, models_key="mk_dev_agents") as api,
        worker(knowledge.files_url, models_url, knowledge.documents_url),
        httpx.Client(base_url=knowledge.files_url, headers=OPS, timeout=30) as files,
        httpx.Client(base_url=knowledge.documents_url, headers=OPS, timeout=30) as documents,
    ):
        fid = upload(files, "levy-notice.pdf", NOTICE)
        ask = {"documentTypeId": "levy_notice", "typeName": "Levy notice"}
        key = {"Idempotency-Key": f"uc244-{uuid.uuid4().hex[:8]}"}
        asked = files.post(f"/v1/files/{fid}/read-requests", json=ask, headers=key)
        request = data(asked) or {}
        followed = until(lambda: started(files, fid, str(request.get("key"))))
        run = until(lambda: settled(api, str(followed["runId"]))) if followed else None
        check(
            "1 a read request starts the system extract workflow as the person, which reads the file and ends saved",
            asked.status_code == 202
            and run is not None
            and run["status"] == "succeeded"
            and run.get("outcome") == "saved"
            and run.get("createdBy") == request.get("requestedBy"),
            {"asked": asked.text[:300], "request": followed, "run": run},
        )
        again = data(files.post(f"/v1/files/{fid}/read-requests", json=ask, headers=key)) or {}
        check(
            "1b the same request again returns the first request and its run",
            again.get("key") == request.get("key") and again.get("runId") == (followed or {}).get("runId"),
            {"again": again, "first": followed},
        )

        saved = data(files.get(f"/v1/files/{fid}")) or {}
        read = saved.get("data") or {}
        listed = data(files.get("/v1/files", params={"readAs": "levy_notice"})) or {}
        check(
            "2 the file carries what was read (type, name, version, extraction) and the list filters by it",
            (read.get("typeId"), read.get("typeName"), read.get("path")) == ("levy_notice", "Levy notice", "model")
            and bool(read.get("extractionId"))
            and isinstance(read.get("version"), int)
            and [r["id"] for r in listed.get("data", [])] == [fid],
            {"data": read, "listed": [r["id"] for r in listed.get("data", [])]},
        )

        got = documents.get(f"/v1/documents/extractions/{read.get('extractionId')}")
        extraction = data(got) or {}
        # The levy notice reads several debtors: correct the first record's first field still waiting, or its first.
        first = (extraction.get("records") or [{}])[0]
        waiting = list(first.get("needsReview") or [])
        field = waiting[0] if waiting else next(iter(first.get("fields") or {}), "")
        patched = documents.patch(
            f"/v1/documents/extractions/{read.get('extractionId')}/fields/{field}",
            json={"value": "Checked value", "record": 0},
        )
        fixed = data(patched) or {}
        after = until(lambda: corrected(files, fid, str(read.get("readAt"))), seconds=60) or {}
        check(
            "2b correcting a field reports extraction.corrected, and the file's saved read follows: one fewer to check",
            ((fixed.get("records") or [{}])[0].get("fields", {}).get(field, {}).get("corrected") is True)
            and after.get("extractionId") == read.get("extractionId")
            and after.get("fieldsToCheck") == len(fixed.get("needsReview") or [])
            and after.get("typeName") == "Levy notice",
            {"patch": patched.text[:300], "field": field, "before": read, "after": after},
        )

        before = data(documents.get("/v1/documents/extractions", params={"fileId": fid})) or {}
        gone = files.delete(f"/v1/files/{fid}")
        purged = until(lambda: purge_run(api), seconds=120)
        check(
            "3 deleting the file reports file.deleted, and the purge workflow removes what was read from it",
            gone.status_code == 204
            and before.get("pagination", {}).get("total", 0) >= 1
            and purged is not None
            and purged["status"] == "succeeded"
            and purged.get("outcome") == "purged",
            {"delete": gone.text[:300], "before": before.get("pagination"), "purge": purged},
        )
        out = (data(api.get(f"/v1/runs/{purged['id']}", headers=OPS)) or {}).get("output") if purged else None
        check(
            "4 the purge removed the file's extractions in documents-service",
            isinstance(out, dict) and int(out.get("extractions") or 0) >= 1,
            out,
        )
    finish()


if __name__ == "__main__":
    main()
