# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-223 documents emailed to a team mailbox become cases, and the sender gets a reply, api layer:
docs/usecases/agents-service/mailed-documents-become-cases.md.

Real mail: the script sends SMTP to GreenMail (compose, `make db-up`), the worker reads the mailbox over IMAP through
tools-service, and the reply leaves through the mailbox's own SMTP sender to Mailpit (compose), which the script reads.
Everything else runs on the script's own ports and database: the fake OpenAI with this use case's rules, models,
kb-service's files-service (scanning off), tools-service with the core fake bank, agents-service and a worker. The
definitions are the dev seed's (mail_intake, mail_document, levy_case), published for team_ops on a fresh mailbox."""

from __future__ import annotations

import io
import json
import os
import signal
import smtplib
import subprocess
import tempfile
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import httpx
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from usecase_harness import (
    AGENTS_DIR,
    AGENTS_PORT,
    DB,
    LOG_DIR,
    ROOT,
    TOOLS_PORT,
    _env,  # pyright: ignore[reportPrivateUsage]
    agents,
    approve_tool_review,
    check,
    data,
    fake_openai,
    finish,
    kb,
    models,
    tools,
)

RULES = AGENTS_DIR / "tests" / "fixtures" / "mail-intake-fake-openai"
NOTICE_PDF = (AGENTS_DIR / "tests" / "fixtures" / "mailbox" / "levy_notice.pdf").read_bytes()
SEED = {w["id"]: w for w in json.loads((AGENTS_DIR / "seed" / "engine_workflows.json").read_text())}
GREENMAIL_SMTP = int(os.environ.get("OPS_GREENMAIL_SMTP_PORT", "3025"))
GREENMAIL_IMAP = int(os.environ.get("OPS_GREENMAIL_IMAP_PORT", "3143"))
MAILPIT_SMTP = int(os.environ.get("OPS_MAILPIT_SMTP_PORT", "1025"))
MAILPIT = f"http://127.0.0.1:{os.environ.get('OPS_MAILPIT_HTTP_PORT', '8025')}"
RUN = uuid.uuid4().hex[:8]
ADDRESS = f"intake-{RUN}@harborpine.test"
IMAP_HOST, SMTP_HOST, SECRET = "mail.harborpine.test", "smtp.harborpine.test", "DEV_IMAP_PASSWORD"
OPS = {"X-Team-Id": "team_ops"}
MAYA = {**OPS, "X-Dev-User": "m.okafor@harborpine.example"}
SECURITY = {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}
SETTLED = ("succeeded", "failed", "cancelled")
CSV = (
    b"name,address,ssn_last4,amount,court,case_no\n"
    b'Priya Natarajan,"88 Lakeshore Road, Toronto ON M8V 1A5",9032,500.00,Ontario Superior Court of Justice,'
    b"ON-2026-CSV-0001\n"
)


def pdf(lines: list[str]) -> bytes:
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=LETTER)
    for i, line in enumerate(lines):
        c.drawString(40, 740 - 16 * i, line)
    c.save()
    return out.getvalue()


# A notice whose debtor the model misreads (the rule answers a name the page does not hold): below the floor.
SMUDGED = pdf(
    [
        "Debtor 1: Ana Example Address: 9 Elm Street, Halifax NS SSN (last four): ***-**-1234",
        "Amount: 100.00 Court: Nova Scotia Supreme Court Case No: NS-2026-GN-09999",
    ]
)


def private_address() -> str:
    import socket  # noqa: PLC0415

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("10.255.255.255", 1))
    address = str(s.getsockname()[0])
    s.close()
    return address


@contextmanager
def core_bank() -> Generator[dict[str, Any]]:
    env = _env() | {"OPS_FAKE_BANK_APP": "core"}
    serve = str(ROOT / "docs" / "usecases" / "lib" / "fake_bank_serve.py")
    argv = ["uv", "run", "--directory", str(AGENTS_DIR), "python", serve]
    proc = subprocess.Popen(argv, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=Path(serve).parent)
    try:
        assert proc.stdout is not None
        yield json.loads(proc.stdout.readline())
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.terminate()
        proc.wait(10)


@contextmanager
def worker(files_url: str, models_url: str, documents_url: str) -> Generator[None]:
    """The workflow worker: it reads the mailbox through tools-service (IMAP) and stores attachments in Files."""
    pg = os.environ.get("OPS_PG_PORT", "5477")
    env = _env() | {
        "OPS_DATABASE_URL": f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}",
        "OPS_MODELS_URL": models_url,
        "OPS_MODELS_KEY": "mk_dev_agents",
        "OPS_FILES_URL": files_url,
        # The Extract from file step reads through documents-service (c-256).
        "OPS_DOCUMENTS_URL": documents_url,
        "OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}",
        "OPS_ENGINE_POLL_SECONDS": "0.2",
        "OPS_EMAIL_POLL_SECONDS": "1",
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "worker-uc223.log").open("ab") as fh:
        argv = ["uv", "run", "python", "-m", "ops_agents.api.worker"]
        proc = subprocess.Popen(argv, cwd=AGENTS_DIR, env=env, stdout=fh, stderr=fh)
    try:
        yield
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def bank_module(gw: httpx.Client) -> None:
    source = {"kind": "openapi", "specUrl": "https://api.bank.test/openapi.json"}
    found = data(gw.post("/v1/tool-modules/discover", json=source))
    ops = [
        {**o, "access": "read" if (o.get("method") or "GET").upper() == "GET" else "write"} for o in found["operations"]
    ]
    body = {
        "name": "northfield-core-banking",
        "displayName": "Harbor & Pine Core Banking",
        "system": found["system"],
        "type": "openapi",
        "endpoint": found["endpoint"],
        "operations": ops,
        "source": source,
    }
    made = data(gw.post("/v1/tool-modules", json=body))
    data(gw.post(f"/v1/tool-modules/{made['id']}/reviews", json={"note": "uc-223"}))
    approve_tool_review(gw, made["id"], SECURITY)


def publish(api: httpx.Client, name: str) -> str:
    d = {k: v for k, v in SEED[name].items() if k != "teamId"}
    for n in d["nodes"]:
        if n["type"] == "ops.trigger.email":
            n["parameters"]["mailbox"] = ADDRESS
    saved = api.post("/v1/workflows/definitions", json={"definition": d}, headers=OPS)
    live = api.post(f"/v1/workflows/definitions/{name}/publish-requests", json={}, headers=OPS)
    return f"{saved.status_code}/{live.status_code}/{live.json().get('data', {}).get('status')}"


def mail(subject: str, files: list[tuple[str, str, bytes]], message_id: str | None = None) -> str:
    """Sends one message to the mailbox through GreenMail's SMTP; returns its Message-ID."""
    m = EmailMessage()
    m["From"] = "registry@court.example"
    m["To"] = ADDRESS
    m["Subject"] = subject
    m["Message-ID"] = message_id or f"<{uuid.uuid4().hex}@court.example>"
    m.set_content("Please find the documents attached.")
    for name, mime, body in files:
        main, sub = mime.split("/")
        m.add_attachment(body, maintype=main, subtype=sub, filename=name)
    with smtplib.SMTP("127.0.0.1", GREENMAIL_SMTP) as s:
        s.send_message(m)
    return str(m["Message-ID"])


def runs(api: httpx.Client, workflow: str) -> list[dict[str, Any]]:
    return list(data(api.get("/v1/runs", params={"workflowId": workflow, "pageSize": 100}, headers=OPS))["data"])


def detail(api: httpx.Client, run_id: str) -> dict[str, Any]:
    return data(api.get(f"/v1/runs/{run_id}", headers=OPS))


def until(fn: Any, seconds: float = 90) -> Any:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if got := fn():
            return got
        time.sleep(0.5)
    return fn()


def resting(api: httpx.Client, workflow: str, count: int) -> list[dict[str, Any]] | None:
    """`count` runs of `workflow`, each waiting for a person or ended; None until then."""
    rs = runs(api, workflow)
    return rs if len(rs) >= count and all(r["status"] in ("waiting", *SETTLED) for r in rs) else None


def settled(api: httpx.Client, run_id: str) -> dict[str, Any] | None:
    """The run once its own steps reached an End: a document run then still waits on the cases it started."""
    d = detail(api, run_id)
    return d if d["outcome"] or d["status"] in SETTLED else None


def replies(subject: str) -> list[dict[str, Any]]:
    r = httpx.get(f"{MAILPIT}/api/v1/search", params={"query": f'subject:"{subject}"'}, timeout=10)
    return [m for m in r.json().get("messages") or [] if m["From"]["Address"] == ADDRESS]


def main() -> None:
    migrate = ["uv", "run", "python", "scripts/scripted_server.py", "--port", "0", "--db", DB, "--migrate-only"]
    subprocess.run(migrate, cwd=AGENTS_DIR, env=_env(), check=True, capture_output=True)
    with (
        tempfile.TemporaryDirectory(prefix="uc223-") as tmp,
        fake_openai(RULES) as fake,
        models({"OPS_MODELS_FAKE_OPENAI_URL": fake}) as models_url,
        # kb-service's files-service is the run's one files-service: agents() would start a second on its port.
        kb(Path(tmp) / "files", models_url=models_url, document_types=True) as knowledge,
        agents(
            kb_url=str(knowledge.base_url).rstrip("/"),
            gateway_url=f"http://127.0.0.1:{TOOLS_PORT}",
            models_url=models_url,
            models_key="mk_dev_agents",
        ) as api,
        # After the services on reserved ports: the bank's own port is the OS's next free one.
        core_bank() as bank,
    ):
        here = private_address()
        resolve = json.loads(bank["settings"]["OPS_EGRESS_RESOLVE"]) | {
            IMAP_HOST: f"{here}:{GREENMAIL_IMAP}",
            SMTP_HOST: f"{here}:{MAILPIT_SMTP}",
        }
        settings = bank["settings"] | {
            "OPS_EGRESS_RESOLVE": json.dumps(resolve),
            "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}",
        }
        with (
            tools(settings=settings) as gw,
            httpx.Client(base_url=knowledge.files_url, timeout=30) as files_api,
        ):
            for host, note in ((bank["host"], "fake bank"), (IMAP_HOST, "GreenMail"), (SMTP_HOST, "Mailpit")):
                gw.post("/v1/egress/hosts", json={"value": host, "note": f"uc-223 {note}"})
            gw.post("/v1/egress/ranges", json={"value": f"{here}/32", "note": "uc-223 this machine"})
            gw.post("/v1/secrets", json={"name": "BANK_API_KEY", "value": "dev-bank-key"})
            gw.post("/v1/secrets", json={"name": SECRET, "value": "any", "teams": ["team_ops"]})
            bank_module(gw)

            # The tenant's limit for case attachments (Settings > Storage): PDFs and CSVs up to 1 MB.
            storage = data(files_api.get("/v1/settings/storage", headers=SECURITY))
            document = storage["document"] | {
                "limits": [{"purpose": "case_attachment", "allowedTypes": ["pdf", "csv"], "maxSizeMb": 1}]
            }
            limited = files_api.put(
                "/v1/settings/storage", json={"version": storage["version"], "document": document}, headers=SECURITY
            )
            form = {
                "name": f"Intake {RUN}",
                "address": ADDRESS,
                "provider": "imap",
                "imapHost": IMAP_HOST,
                "imapPort": 143,
                "imapTls": False,
                "passwordSecret": SECRET,
                "sender": "smtp",
                "fromAddress": ADDRESS,
                "smtpHost": SMTP_HOST,
                "smtpPort": 587,
                "smtpStarttls": False,
                "senderSecret": SECRET,
            }
            connected = api.post("/v1/channels/mailboxes", json=form, headers=OPS)
            published = [publish(api, n) for n in ("levy_case", "mail_document", "mail_intake")]
            check(
                "1 setup: a 1 MB PDF-or-CSV limit, the team mailbox with its own sender, the workflows published",
                limited.status_code == 200 and connected.status_code == 201 and published == ["201/201/approved"] * 3,
                {"limit": limited.text[:200], "mailbox": connected.text[:200], "published": published},
            )

            with worker(knowledge.files_url, models_url, knowledge.documents_url):
                time.sleep(31)  # agents-service keeps each tenant's tool list for 30 seconds; the first pass syncs
                first = f"Garnishment documents {RUN}"
                first_files = [
                    ("notice-of-garnishment.pdf", "application/pdf", NOTICE_PDF),
                    # Mail clients often send a CSV as octet-stream; files-service judges it by its bytes (c-234).
                    ("debtors.csv", "application/octet-stream", CSV),
                    ("scan-archive.pdf", "application/pdf", b"%PDF-1.4\n" + b"0" * (2 * 1024 * 1024)),
                    ("viewer.exe", "application/octet-stream", b"MZ\x90\x00"),
                ]
                message_id = mail(first, first_files)
                # The intake's own steps end once it has started each document; it then waits on them.
                intake = until(lambda: [r for r in runs(api, "mail_intake") if r["outcome"] or r["status"] in SETTLED])
                got = (intake or [{}])[0].get("input") or {}
                check(
                    "2 the PDF and the CSV are stored by id; the 2 MB file and the .exe are listed as skipped with why",
                    [a["name"] for a in got.get("attachments", [])] == ["notice-of-garnishment.pdf", "debtors.csv"]
                    and all(a.get("fileId") for a in got.get("attachments", []))
                    and [(s["name"], s["reason"]) for s in got.get("skipped", [])]
                    == [("scan-archive.pdf", "too_large"), ("viewer.exe", "type_not_allowed")],
                    {"attachments": got.get("attachments"), "skipped": got.get("skipped")},
                )
                docs = until(lambda: resting(api, "mail_document", 2)) or []
                cases = until(lambda: resting(api, "levy_case", 4)) or []
                names = sorted((c["input"]["record"]["name"], c["status"]) for c in cases)
                check(
                    "3 each attachment is read in its own run; every debtor opens a case, matched ones wait for review",
                    len(docs) == 2
                    and {d["status"] for d in docs} == {"waiting"}
                    and names
                    == [
                        ("Jordan Whitfield", "succeeded"),
                        ("Marcus Bell", "waiting"),
                        ("Priya Natarajan", "waiting"),
                        ("Priya Natarajan", "waiting"),
                    ],
                    {"documents": [(d["status"], d["outcome"], d["error"]) for d in docs], "cases": names},
                )

                pdf_doc = next(d for d in docs if d["input"]["name"] == "notice-of-garnishment.pdf")
                ack = api.post(f"/reviews/{pdf_doc['id']}/decision", json={"decision": "approved"}, headers=MAYA)
                done = until(lambda: settled(api, pdf_doc["id"]))
                sent = until(lambda: replies(first), 30) or []
                check(
                    "4 Maya approves the acknowledgement: one reply leaves from the team mailbox to the sender",
                    ack.status_code == 200
                    and (done or {}).get("outcome") == "replied"
                    and len(sent) == 1
                    and sent[0]["To"][0]["Address"] == "registry@court.example",
                    {"decision": ack.text[:200], "run": (done or {}).get("outcome"), "replies": sent},
                )

                second = f"Smudged notice {RUN}"
                mail(second, [("smudged.pdf", "application/pdf", SMUDGED)])
                low = until(
                    lambda: next(
                        (
                            d
                            for d in runs(api, "mail_document")
                            if d["input"]["name"] == "smudged.pdf" and d["status"] == "waiting"
                        ),
                        None,
                    )
                )
                waiting_on = ((low or {}).get("waiting") or {}).get("node")
                rejected = api.post(
                    f"/reviews/{(low or {}).get('id')}/decision", json={"decision": "rejected"}, headers=MAYA
                )
                ended = until(lambda: settled(api, low["id"])) if low else None
                check(
                    "5 a read below the floor waits on Check the read; rejected, it ends needs_manual_read, no case",
                    waiting_on == "check"
                    and rejected.status_code == 200
                    and (ended or {}).get("outcome") == "needs_manual_read"
                    and len(runs(api, "levy_case")) == 4,
                    {"waiting": waiting_on, "decision": rejected.text[:200], "run": (ended or {}).get("outcome")},
                )

                # The same message again: a redelivery. Another message reusing its Message-ID would run (c-231).
                mail(first, first_files, message_id=message_id)
                time.sleep(6)
                check(
                    "6 the first message delivered again starts no run and opens no case",
                    len(runs(api, "mail_intake")) == 2 and len(runs(api, "levy_case")) == 4,
                    {"intakes": len(runs(api, "mail_intake")), "cases": len(runs(api, "levy_case"))},
                )
    finish()


if __name__ == "__main__":
    main()
