# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-200 a reply leaves from the team mailbox the customer wrote to, api layer:
docs/usecases/agents-service/reply-from-a-team-mailbox.md.

Runs against the shared stack (`OPS_STACK_AUTH=platform make up`, Mailpit in compose). The approval token is minted
with the dev review key, as the review service signs one, and the call carries a workflow's service token naming
team_ops, as the worker's does."""

from __future__ import annotations

import os
import socket
import time
import uuid

import httpx
from usecase_harness import check, finish, service_headers

from ops_service_kit.ids import input_hash
from ops_tools.tokens import Binding, mint

PLATFORM = f"http://127.0.0.1:{os.environ.get('OPS_PLATFORM_PORT', '8710')}"
AGENTS = f"http://127.0.0.1:{os.environ.get('OPS_AGENTS_PORT', '8700')}"
TOOLS = f"http://127.0.0.1:{os.environ.get('OPS_TOOLS_PORT', '8720')}"
MAILPIT = f"http://127.0.0.1:{os.environ.get('OPS_MAILPIT_HTTP_PORT', '8025')}"
REVIEW_KEY = "dev-review-key-not-secret"
SMTP_HOST, IMAP_HOST, SECRET = "smtp.harborpine.test", "mail.harborpine.test", "DEV_IMAP_PASSWORD"
RUN = uuid.uuid4().hex[:8]
ADDRESS, FROM = f"desk-{RUN}@harborpine.test", f"replies-{RUN}@harborpine.test"
SUBJECT = f"Your levy notice {RUN}"
THREAD = f"uc200_{RUN}"


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


def reply(team: str, step: str) -> httpx.Response:
    doc = {"to": "ana@example.com", "subject": SUBJECT, "body": "We have placed the hold.", "mailbox": ADDRESS}
    token = mint(
        Binding(THREAD, step, "send_reply", input_hash(doc), ["m.okafor@harborpine.example"]), REVIEW_KEY, ttl_s=300
    )
    return httpx.post(
        f"{TOOLS}/v1/calls",
        headers=service_headers("tools", team=team),
        json={
            "tool": "send_reply",
            "input": doc,
            "key": step,
            "runContext": {"thread": THREAD, "step": step, "act": "usecase"},
            "approvalToken": token,
        },
        timeout=60,
    )


def delivered() -> list[dict]:
    time.sleep(1)
    r = httpx.get(f"{MAILPIT}/api/v1/search", params={"query": f'subject:"{SUBJECT}"'}, timeout=10)
    return r.json().get("messages") or []


sam = headers("s.adeyemi@harborpine.example", "team_security")
james = headers("j.richardson@harborpine.example", "team_ops")
tools = httpx.Client(base_url=TOOLS, timeout=30)
api = httpx.Client(base_url=AGENTS, timeout=60)

made = tools.post("/v1/secrets", json={"name": SECRET, "value": "app-password", "teamId": "team_ops"}, headers=sam)
tools.post("/v1/egress/hosts", json={"value": SMTP_HOST, "note": "uc-200 Mailpit"}, headers=sam)
tools.post("/v1/egress/ranges", json={"value": f"{private_address()}/32", "note": "uc-200 Mailpit"}, headers=sam)
check("0 the secret and the SMTP host are in place", made.status_code in (201, 409), made.text[:200])

form = {
    "name": f"Levy desk {RUN}",
    "address": ADDRESS,
    "provider": "imap",
    "imapHost": IMAP_HOST,
    "imapPort": 143,
    "imapTls": False,
    "passwordSecret": SECRET,
    "sender": "smtp",
    "fromAddress": FROM,
    "smtpHost": SMTP_HOST,
    "smtpPort": 587,
    "smtpStarttls": False,
    "senderSecret": SECRET,
}
connected = api.post("/v1/channels/mailboxes", json=form, headers=james)
m = connected.json().get("data", {})
check(
    "1 James connects a mailbox with its own reply sender",
    connected.status_code == 201 and m.get("sender") == "smtp" and m.get("fromAddress") == FROM,
    connected.text[:300],
)

sent = reply("team_ops", f"{THREAD}:reply:1")
data = sent.json().get("data", {})
found = delivered()
check(
    "2 a team_ops call naming the mailbox sends from its from address",
    sent.status_code == 200 and data.get("ok") is True and [x["From"]["Address"] for x in found] == [FROM],
    (sent.text[:300], found),
)

again = reply("team_ops", f"{THREAD}:reply:1")
check(
    "3 the same key again is replayed and Mailpit still has one copy",
    again.status_code == 200 and again.json()["data"].get("replayOf") and len(delivered()) == 1,
    again.text[:300],
)

other = reply("team_fraud", f"{THREAD}:reply:2")
out = other.json().get("data", {})
check(
    "4 a team_fraud call sends nothing and says why",
    other.status_code == 200
    and out.get("ok") is False
    and "not a mailbox of team_fraud" in str(out.get("output"))
    and len(delivered()) == 1,
    other.text[:300],
)

finish()
