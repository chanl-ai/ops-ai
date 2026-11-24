# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-772 A read no model reply answered goes to a person, api layer:
docs/usecases/documents-service/a-read-no-model-reply-answered.md.

Own services, no real model: models-service on the fake OpenAI with the documents fixtures' rules and, ahead of them,
two invoices whose extraction reply is cut off at the output limit or declined; files-service delivering its events to
this run's agents-service, documents-service with the seeded document types, agents-service with its shipped
system_extract workflow, and a workflow worker. Each file is read with Detect, as the Files page asks."""

from __future__ import annotations

import hashlib
import io
import json
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
    pg_url,
)

DOCS = ROOT / "services" / "documents-service"
RULES = DOCS / "tests" / "fixtures" / "fake-model" / "script.json"
SEED = ROOT / "services" / "agents-service" / "seed" / "event_workflows.json"
INVOICES = DOCS / "tests" / "fixtures" / "invoice"
OPS = {"X-Team-Id": "team_ops"}
MAYA = {**OPS, "X-Dev-User": "m.okafor@harborpine.example"}
SETTLED = {"succeeded", "failed", "cancelled"}
CUT, DECLINED = "INV-77201", "INV-77202"
TYPED = {"invoice_no": CUT, "vendor": "Lakeshore Freight Co", "total": "1,940.00"}


def rules(folder: Path) -> Path:
    """The documents fixtures' rules with two invoices ahead of them: Detect finds each a supplier invoice, and the
    extraction reply is cut off at the output limit (every time, so the retry is cut off too) or declined."""
    base = json.loads(RULES.read_text())
    ours: list[dict[str, Any]] = []
    for number, ending in ((CUT, "length"), (DECLINED, "refusal")):
        marker = number.replace("-", "\\-")
        ours.append(
            {
                "when": f"^Document types:.*{marker}",
                "tool": "final_result",
                "arguments": {"typeId": "supplier_invoice", "confidence": 0.95, "reason": f"{number} is printed"},
            }
        )
        ours.append(
            {
                "when": f"^Fields:.*{marker}",
                "tool": "final_result",
                "arguments": {"invoice_no": {"value": number, "quote": number, "page": 1}},
                "finish": ending,
            }
        )
    (folder / "script.json").write_text(json.dumps({**base, "rules": ours + base["rules"]}))
    return folder


def invoice(number: str) -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica", 12)
    lines = [
        "Lakeshore Freight Co",
        f"Invoice {number}",
        "Bill to: Northfield Bank Facilities",
        "Invoice date: 10/14/2026   Due date: 11/13/2026",
        "Total due: $1,940.00",
    ]
    for i, line in enumerate(lines):
        c.drawString(72, 700 - 24 * i, line)
    c.save()
    return buf.getvalue()


def before_typed_values() -> dict[str, Any]:
    """system_extract as it shipped before its check took typed values: no editable, approve straight to the save."""
    seeded = next(w for w in json.loads(SEED.read_text()) if w["id"] == "system_extract")
    nodes = [dict(n) for n in seeded["nodes"] if n["id"] != "save_typed"]
    for n in nodes:
        if n["id"] == "check":
            n["parameters"] = {k: v for k, v in n["parameters"].items() if k != "editable"}
    edges = [e for e in seeded["connections"] if "save_typed" not in (e["from"]["node"], e["to"]["node"])]
    edges.append({"from": {"node": "check", "port": "approve"}, "to": {"node": "save_checked", "port": "in"}})
    return {**seeded, "nodes": nodes, "connections": edges}


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
    with (LOG_DIR / "worker-uc772.log").open("ab") as fh:
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


def read_run(files: httpx.Client, fid: str) -> str:
    """Asks Files to read the file with Detect, as the Files page does, and returns the run it started."""
    asked = files.post(f"/v1/files/{fid}/read-requests", json={}, headers={"Idempotency-Key": uuid.uuid4().hex})
    key = str((data(asked) or {}).get("key"))

    def started() -> str | None:
        found = data(files.get(f"/v1/files/{fid}/read-requests/{key}")) or {}
        return str(found["runId"]) if found.get("runId") else None

    return str(until(started))


def run_in(api: httpx.Client, run_id: str, states: set[str]) -> dict[str, Any] | None:
    run = data(api.get(f"/v1/runs/{run_id}", headers=OPS)) or {}
    return run if run.get("status") in states else None


def task(api: httpx.Client, files: httpx.Client, fid: str) -> tuple[str, dict[str, Any]]:
    """A read of the file that waits for a person, and its task as Human Tasks reads it."""
    run_id = read_run(files, fid)
    until(lambda: run_in(api, run_id, {"waiting"} | SETTLED))
    return run_id, data(api.get(f"/reviews/{run_id}", headers=MAYA)) or {}


def publish(api: httpx.Client, definition: dict[str, Any]) -> dict[str, Any]:
    """A person saves `definition` as system_extract's next version and publishes it, as a builder does."""
    saved = data(api.post("/v1/workflows/definitions", json={"definition": definition}, headers=OPS)) or {}
    body = {"version": saved.get("version")}
    return data(api.post("/v1/workflows/definitions/system_extract/publish-requests", json=body, headers=OPS)) or {}


def update(api: httpx.Client, live: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    """A person publishes `definition` over the `live` version through the editor's working copy, which makes a new
    version even when the same definition was published before (the shipped one, provisioned first)."""
    base = {"baseVersion": live["publish"]["toVersion"], "baseDigest": live["publish"]["digest"]}
    url = "/v1/workflows/definitions/system_extract"
    saved = data(api.put(f"{url}/working-copy", json={"definition": definition, **base}, headers=OPS)) or {}
    copy = saved.get("saveBase") or {}
    body = {"baseVersion": copy.get("version"), "baseDigest": copy.get("digest")}
    return data(api.post(f"{url}/publish-requests", json=body, headers=OPS)) or {}


def decide(api: httpx.Client, run_id: str, **body: Any) -> httpx.Response:
    return api.post(f"/reviews/{run_id}/decision", json={"decision": "approved", **body}, headers=MAYA)


def main() -> None:
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    agents_url = f"http://127.0.0.1:{AGENTS_PORT}"
    with (
        tempfile.TemporaryDirectory(prefix="uc772-") as tmp,
        fake_openai(rules(Path(tmp))) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        kb(Path(tmp) / "files", models_url=models_url, document_types=True, agents_url=agents_url) as knowledge,
        agents(kb_url=str(knowledge.base_url).rstrip("/"), models_url=models_url, models_key="mk_dev_agents") as api,
        worker(knowledge.files_url, models_url, knowledge.documents_url),
        httpx.Client(base_url=knowledge.files_url, headers=OPS, timeout=30) as files,
        httpx.Client(base_url=knowledge.documents_url, headers=OPS, timeout=30) as documents,
    ):
        # The first read request provisions the shipped system_extract, which a person then replaces with the version
        # from before it took typed values: a tenant that has not taken the update yet.
        first = upload(files, "INVA01.pdf", (INVOICES / "INVA01.pdf").read_bytes())
        until(lambda: run_in(api, read_run(files, first), SETTLED))
        old = publish(api, before_typed_values())

        cut = upload(files, "lakeshore-77201.pdf", invoice(CUT))
        run_id, review = task(api, files, cut)
        read = review.get("read") or {}
        refused = decide(api, run_id, inputs={"edited": [{"values": TYPED}]})
        rejected = api.post(
            f"/reviews/{run_id}/decision", json={"decision": "rejected", "reason": "Read it again"}, headers=MAYA
        )
        done = until(lambda: run_in(api, run_id, SETTLED))
        check(
            "1 on a tenant without the update, a cut-off read goes to review saying why, and can only be rejected",
            old.get("status") == "approved"
            and read.get("notRead") == "cut_off"
            and read.get("editable") is False
            and (read.get("approveRefused") or {}).get("code") == "not_editable"
            and "the reply was cut off" in str(review.get("proposal"))
            and refused.status_code == 400
            and (refused.json().get("error") or {}).get("code") == "not_editable"
            and rejected.status_code == 200
            and (done or {}).get("outcome") == "needs_manual_read"
            and not (data(files.get(f"/v1/files/{cut}")) or {}).get("data"),
            {"old": old.get("status"), "read": read, "refused": refused.text[:300], "done": (done or {}).get("outcome")},
        )

        # The update: the shipped version published again, as an admin approving it in Reviews makes it live.
        seeded = next(w for w in json.loads(SEED.read_text()) if w["id"] == "system_extract")
        updated = update(api, old, seeded)
        run_id, review = task(api, files, cut)
        read = review.get("read") or {}
        empty = decide(api, run_id)
        confirmed = {"0": ["invoice_no", "total"]}
        typed = decide(api, run_id, inputs={"edited": [{"values": TYPED}], "confirmed": confirmed})
        done = until(lambda: run_in(api, run_id, SETTLED))
        saved = (data(files.get(f"/v1/files/{cut}")) or {}).get("data") or {}
        check(
            "2 after the update the rejected file is read again without uploading it, and the task takes typed values",
            updated.get("status") == "approved"
            and read.get("notRead") == "cut_off"
            and read.get("editable") is True
            and read.get("approveRefused") is None
            and empty.status_code == 400
            and (empty.json().get("error") or {}).get("code") == "required_fields_empty"
            and typed.status_code == 200
            and (done or {}).get("outcome") == "saved"
            and saved.get("typeId") == "supplier_invoice"
            and saved.get("fieldsToCheck") == 0,
            {
                "updated": {k: updated.get(k) for k in ("status", "publish", "error")},
                "read": {k: read.get(k) for k in ("notRead", "editable", "approveRefused")},
                "empty": empty.text[:300],
                "typed": typed.text[:300],
                "done": (done or {}).get("outcome"),
                "data": saved,
            },
        )

        extraction = data(documents.get(f"/v1/documents/extractions/{saved.get('extractionId')}")) or {}
        rows = {c["field"]: c for c in extraction.get("corrections") or []}
        check(
            "3 the typed values are saved on the read with the person who typed them and no original value",
            set(rows) == set(TYPED)
            and all(c.get("original") is None for c in rows.values())
            and {c.get("correctedBy") for c in rows.values()} == {MAYA["X-Dev-User"]}
            and rows.get("total", {}).get("corrected") == 1940,
            {"outcome": extraction.get("outcome"), "corrections": list(rows.values())},
        )

        declined = upload(files, "lakeshore-77202.pdf", invoice(DECLINED))
        run_id, review = task(api, files, declined)
        read = review.get("read") or {}
        check(
            "4 a declined reply goes to review as declined, with every field not read",
            read.get("notRead") == "declined"
            and "the model declined" in str(review.get("proposal"))
            and all(v is None for r in read.get("records") or [] for v in r.get("values", {}).values()),
            {"read": read, "proposal": review.get("proposal")},
        )
    finish()


if __name__ == "__main__":
    main()
