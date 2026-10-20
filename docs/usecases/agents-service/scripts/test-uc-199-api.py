# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-199 a builder connects a team mailbox and binds a workflow to it, api layer:
docs/usecases/agents-service/connect-a-mailbox.md.

Runs against the shared stack (`OPS_STACK_AUTH=platform make up`, GreenMail and Mailpit in compose). Sam puts the
password on the Secrets page and lists the GreenMail host; James connects a new IMAP mailbox through
/v1/channels/mailboxes with no settings edit or restart, tests it, binds a workflow, pauses and resumes it; mail sent
to GreenMail starts one run only while the mailbox runs. A viewer cannot connect one and another team cannot see it."""

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
SMTP = int(os.environ.get("OPS_GREENMAIL_SMTP_PORT", "3025"))
HOST, SECRET = "mail.northfield.test", "DEV_IMAP_PASSWORD"
RUN = uuid.uuid4().hex[:8]
ADDRESS = f"desk-{RUN}@northfield.test"
WID = f"uc199_{RUN}"
POLL = float(os.environ.get("OPS_EMAIL_POLL_SECONDS", "3"))


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


def send(subject: str) -> None:
    m = EmailMessage()
    m["From"] = "registry@court.example"
    m["To"] = ADDRESS
    m["Subject"] = subject
    m["Message-ID"] = f"<{uuid.uuid4().hex}@court.example>"
    m.set_content("A notice.")
    with smtplib.SMTP("127.0.0.1", SMTP) as s:
        s.send_message(m)


sam = headers("s.adeyemi@northfieldbank.com", "team_security")
james = headers("j.richardson@northfieldbank.com", "team_ops")
ravi = headers("r.menon@northfieldbank.com", "team_ops")
omar = headers("o.haddad@northfieldbank.com", "team_fraud")
tools = httpx.Client(base_url=TOOLS, timeout=30)
api = httpx.Client(base_url=AGENTS, timeout=60)

made = tools.post("/v1/secrets", json={"name": SECRET, "value": "app-password", "teams": ["team_ops"]}, headers=sam)
tools.post("/v1/egress/hosts", json={"value": HOST, "note": "uc-199 GreenMail"}, headers=sam)
tools.post("/v1/egress/ranges", json={"value": f"{private_address()}/32", "note": "uc-199 GreenMail"}, headers=sam)
check("0 the secret and the mail host are in place", made.status_code in (201, 409), made.text[:200])

form: dict[str, Any] = {
    "name": f"Service desk {RUN}",
    "address": ADDRESS,
    "provider": "imap",
    "imapHost": HOST,
    "imapPort": 143,
    "imapTls": False,
    "passwordSecret": SECRET,
}
refused = api.post("/v1/channels/mailboxes", json=form, headers=ravi)
check("1 a viewer cannot connect a mailbox (403)", refused.status_code == 403, refused.text[:200])

send(f"Before connecting {RUN}")
tested = api.post("/v1/channels/mailboxes/test", json=form, headers=james)
t = tested.json().get("data", {})
check(
    "2 Test connection on the unsaved form signs in and reads the newest message",
    tested.status_code == 200 and t.get("ok") is True and RUN in (t.get("newest") or {}).get("subject", ""),
    tested.text[:300],
)
connected = api.post("/v1/channels/mailboxes", json=form, headers=james)
mailbox = connected.json().get("data", {})
check("3 James connects it with no settings edit or restart", connected.status_code == 201, connected.text[:300])
mid = mailbox.get("id", "")
listed = [m["address"] for m in api.get("/v1/channels/mailboxes", headers=james).json()["data"]]
other = api.get(f"/v1/channels/mailboxes/{mid}", headers=omar)
check(
    "4 the team lists it; another team's builder gets 404",
    ADDRESS in listed and other.status_code == 404,
    other.status_code,
)

options = api.get("/v1/workflows/option-sources", params={"source": "mailboxes"}, headers=james).json()["data"]
check("5 the trigger's picker offers it", ADDRESS in [o["value"] for o in options], options)

definition = {
    "schemaVersion": 2,
    "id": WID,
    "name": f"Service desk intake {RUN}",
    "nodes": [
        {
            "id": "start",
            "type": "ops.trigger.email",
            "typeVersion": 1,
            "name": "Email received",
            "parameters": {"mailbox": ADDRESS, "folder": "inbox"},
        },
        {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
    ],
    "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
}
saved = api.post("/v1/workflows/definitions", json={"definition": definition}, headers=james)
live = api.post(f"/v1/workflows/definitions/{WID}/publish-requests", json={}, headers=james)
check("6 James binds a workflow to it", saved.status_code == 201 and live.status_code == 201, live.text[:300])


def runs() -> list[dict[str, Any]]:
    return list(api.get("/v1/runs", params={"workflowId": WID, "pageSize": 100}, headers=james).json()["data"]["data"])


time.sleep(POLL * 3)  # the first pass takes the cursor
try:
    paused = api.patch(f"/v1/channels/{mid}", json={"paused": True}, headers=james)
    send(f"While paused {RUN}")
    time.sleep(POLL * 3)
    check("7 a paused mailbox starts nothing", paused.status_code == 200 and runs() == [], runs())
    api.patch(f"/v1/channels/{mid}", json={"paused": False}, headers=james)
    end = time.monotonic() + 45
    while time.monotonic() < end and not runs():
        time.sleep(1)
    found = runs()
    check("8 on resume the mail that arrived meanwhile starts its run", len(found) == 1, found)
    view = api.get(f"/v1/channels/mailboxes/{mid}", headers=james).json()["data"]
    check(
        "9 the mailbox page lists the bound workflow and when it was last read",
        [w["id"] for w in view["workflows"]] == [WID] and bool(view["lastReadAt"]),
        view,
    )
finally:
    api.post(f"/v1/workflows/definitions/{WID}/pause", headers=james)
finish()
