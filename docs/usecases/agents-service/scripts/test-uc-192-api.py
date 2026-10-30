# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-192 an email in an IMAP mailbox starts a workflow, api layer:
docs/usecases/agents-service/imap-mailbox-starts-a-workflow.md.

Runs against the shared stack (`OPS_STACK_AUTH=platform make up`, which also starts GreenMail and Mailpit in
compose). The steps a bank's admins take for a real mailbox, on GreenMail: James puts the mailbox password on
Operations' Secrets page, Sam lists the mail host and its address on the Egress page, and James binds a workflow to
intake@harborpine.test; an email with a PDF is sent to GreenMail over SMTP; the worker reads it over IMAP through
tools-service and starts one run with the PDF in Files. No model call is made."""

from __future__ import annotations

import os
import smtplib
import socket
import time
import uuid
from email.message import EmailMessage
from typing import Any

import httpx
from usecase_harness import check, finish

PLATFORM = f"http://127.0.0.1:{os.environ.get('OPS_PLATFORM_PORT', '8710')}"
AGENTS = f"http://127.0.0.1:{os.environ.get('OPS_AGENTS_PORT', '8700')}"
TOOLS = f"http://127.0.0.1:{os.environ.get('OPS_TOOLS_PORT', '8720')}"
FILES = f"http://127.0.0.1:{os.environ.get('OPS_FILES_PORT', '8750')}"
SMTP = int(os.environ.get("OPS_GREENMAIL_SMTP_PORT", "3025"))
MAILBOX, HOST, SECRET = "intake@harborpine.test", "mail.harborpine.test", "DEV_IMAP_PASSWORD"
PDF = b"%PDF-1.4 uc-192 notice"
RUN = uuid.uuid4().hex[:8]
WID = f"uc192_{RUN}"
WAIT_S = float(os.environ.get("UC192_WAIT_S", "45"))


def headers(email: str, team: str) -> dict[str, str]:
    r = httpx.post(f"{PLATFORM}/v1/auth/sign-in", json={"email": email, "password": "northfield-demo"}, timeout=30)
    assert r.status_code == 200, f"sign-in as {email}: {r.status_code} {r.text[:200]}"
    return {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": team}


def private_address() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("10.255.255.255", 1))
    address = str(s.getsockname()[0])
    s.close()
    return address


def send(subject: str, message_id: str) -> None:
    m = EmailMessage()
    m["From"] = "registry@court.example"
    m["To"] = MAILBOX
    m["Subject"] = subject
    m["Message-ID"] = message_id
    m.set_content("Please hold the amounts in the attached notice.")
    m.add_attachment(PDF, maintype="application", subtype="pdf", filename="notice.pdf")
    with smtplib.SMTP("127.0.0.1", SMTP) as s:
        s.send_message(m)


def until(what: str, probe: Any, timeout: float = WAIT_S) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if found := probe():
            return found
        time.sleep(1)
    raise TimeoutError(f"waited {timeout:.0f}s for {what}")


sam = headers("s.adeyemi@harborpine.example", "team_security")
james = headers("j.richardson@harborpine.example", "team_ops")
tools = httpx.Client(base_url=TOOLS, timeout=30)
api = httpx.Client(base_url=AGENTS, headers=james, timeout=30)

# A secret belongs to the team that uses it and that team's builders keep it: James, for Operations. Sam, Security's
# admin, keeps egress.
made = tools.post("/v1/secrets", json={"name": SECRET, "value": "app-password"}, headers=james)
if made.status_code == 409:
    made = tools.post(f"/v1/secrets/{SECRET}/rotate", json={"value": "app-password"}, headers=james)
host = tools.post("/v1/egress/hosts", json={"value": HOST, "note": "uc-192 GreenMail"}, headers=sam)
rng = tools.post(
    "/v1/egress/ranges", json={"value": f"{private_address()}/32", "note": "uc-192 GreenMail"}, headers=sam
)
check(
    "1 James puts the mailbox password on Operations' Secrets page; Sam lists the mail host and its address",
    made.status_code in (200, 201) and host.status_code in (200, 201, 409) and rng.status_code in (200, 201, 409),
    f"{made.status_code} {host.status_code} {rng.status_code} {made.text[:200]}",
)

options = api.get("/v1/workflows/option-sources", params={"source": "mailboxes"}).json()["data"]
offered = {o["value"]: o["description"] for o in options}
check("2 the mailbox picker offers the IMAP mailbox as IMAP", offered.get(MAILBOX) == f"{MAILBOX} · IMAP", offered)

definition = {
    "schemaVersion": 2,
    "id": WID,
    "name": f"IMAP intake {RUN}",
    "nodes": [
        {
            "id": "start",
            "type": "ops.trigger.email",
            "typeVersion": 1,
            "name": "Email received",
            "parameters": {"mailbox": MAILBOX, "folder": "inbox", "subjectContains": RUN, "hasAttachment": True},
        },
        {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
    ],
    "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
}
saved = api.post("/v1/workflows/definitions", json={"definition": definition})
published = api.post(f"/v1/workflows/definitions/{WID}/publish-requests", json={})
check(
    "3 James binds a workflow to the mailbox",
    saved.status_code == 201 and published.status_code == 201,
    published.text[:300],
)


def runs() -> list[dict[str, Any]]:
    r = api.get("/v1/runs", params={"workflowId": WID, "pageSize": 100})
    assert r.status_code == 200, r.text[:200]
    return list(r.json()["data"]["data"])


send(f"Before the trigger {RUN}", f"<before-{RUN}@court.example>")  # history by the time the first pass runs
time.sleep(float(os.environ.get("OPS_EMAIL_POLL_SECONDS", "3")) * 3)
check("4 mail already in the mailbox started no run", runs() == [], runs())

try:
    send(f"Notice of garnishment {RUN}", f"<notice-{RUN}@court.example>")
    started = time.monotonic()
    [run] = until("the run", lambda: runs() or None)
    detail = api.get(f"/v1/runs/{run['id']}").json()["data"]
    inp = detail["input"]
    check(
        "5 the email started one run with the PDF as a Files id",
        inp["mailbox"] == MAILBOX and RUN in inp["subject"] and len(inp["attachments"]) == 1,
        inp,
    )
    print(f"     run started {time.monotonic() - started:.1f}s after the email was sent")
    got = httpx.get(f"{FILES}/v1/files/{inp['attachments'][0]['fileId']}/content", headers=james, timeout=30)
    check("6 the PDF is in Files, byte for byte", got.status_code == 200 and got.content == PDF, got.status_code)
    send(f"Notice of garnishment {RUN}", f"<notice-{RUN}@COURT.example>")  # the same message delivered again
    time.sleep(float(os.environ.get("OPS_EMAIL_POLL_SECONDS", "3")) * 3)
    check("7 a redelivery started no second run", len(runs()) == 1, runs())
    # A secret belongs to its team, so Operations' own list shows its use; Security's list holds only its own.
    secret = next((s for s in tools.get("/v1/secrets", headers=james).json()["data"] if s["name"] == SECRET), {})
    check(
        "8 tools-service read the secret (its use is recorded) and no response carried the password",
        bool(secret.get("lastUsedAt")) and "app-password" not in str(detail) and "app-password" not in str(secret),
        secret,
    )
except TimeoutError as e:
    check("5 the email started one run", False, str(e))
finally:
    api.post(f"/v1/workflows/definitions/{WID}/pause")
finish()
