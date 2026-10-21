"""uc-150 an email in a watched mailbox starts a workflow, api layer:
docs/usecases/agents-service/email-starts-a-workflow.md.

Runs against the shared stack (`make up` with OPS_STACK_AUTH=platform): platform-service signs James in,
agents-service saves and publishes a workflow whose trigger is Email received on the team mailbox, the notice is
emailed to that mailbox on the stack's GreenMail, the workflow worker reads it over IMAP through tools-service, and
files-service holds the attachment. This workflow makes no model call; the seeded levy_intake, when live on the same
mailbox, also reads the notice."""

from __future__ import annotations

import base64
import json
import os
import smtplib
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import check, finish

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "services" / "agents-service" / "scripts"))
from send_levy_email import message  # noqa: E402

PLATFORM = f"http://127.0.0.1:{os.environ.get('OPS_PLATFORM_PORT', '8710')}"
AGENTS = f"http://127.0.0.1:{os.environ.get('OPS_AGENTS_PORT', '8700')}"
FILES = f"http://127.0.0.1:{os.environ.get('OPS_FILES_PORT', '8750')}"
MAILBOX = os.environ.get("UC150_MAILBOX", "levy@harborpine.example")
GREENMAIL_SMTP = int(os.environ.get("OPS_GREENMAIL_SMTP_PORT", "3025"))
NOTICE: dict[str, Any] = json.loads(
    (ROOT / "services" / "agents-service" / "tests" / "fixtures" / "mailbox" / "levy_notice.json").read_text()
)
PDF = base64.b64decode(NOTICE["attachments"][0]["contentBytes"])
RUN = uuid.uuid4().hex[:8]
WID = f"uc150_{RUN}"
WAIT_S = float(os.environ.get("UC150_WAIT_S", "30"))


def token(email: str) -> str:
    r = httpx.post(f"{PLATFORM}/v1/auth/sign-in", json={"email": email, "password": "northfield-demo"}, timeout=30)
    assert r.status_code == 200, f"sign-in as {email}: {r.status_code} {r.text[:200]}"
    return str(r.json()["data"]["token"])


def send(message_id: str) -> None:
    """The levy notice under `message_id`, emailed to the mailbox through GreenMail's SMTP."""
    with smtplib.SMTP("127.0.0.1", GREENMAIL_SMTP) as s:
        s.send_message(message(NOTICE | {"internetMessageId": message_id}, MAILBOX))


def until(what: str, probe: Any, timeout: float = WAIT_S) -> Any:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if found := probe():
            return found
        time.sleep(1)
    raise TimeoutError(f"waited {timeout:.0f}s for {what}")


james = {"Authorization": f"Bearer {token('j.richardson@harborpine.example')}", "X-Team-Id": "team_ops"}
api = httpx.Client(base_url=AGENTS, headers=james, timeout=30)

options = api.get("/v1/workflows/option-sources", params={"source": "mailboxes"})
check(
    "1 the mailbox picker offers the team mailbox",
    options.status_code == 200 and MAILBOX in [o["value"] for o in options.json()["data"]],
    options.text[:300],
)

definition = {
    "schemaVersion": 2,
    "id": WID,
    "name": f"Levy intake {RUN}",
    "nodes": [
        {
            "id": "start",
            "type": "ops.trigger.email",
            "typeVersion": 1,
            "name": "Email received",
            "parameters": {
                "mailbox": MAILBOX,
                "folder": "inbox",
                "fromContains": "@court.example",
                "hasAttachment": True,
            },
        },
        {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
    ],
    "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
}
saved = api.post("/v1/workflows/definitions", json={"definition": definition})
published = api.post(f"/v1/workflows/definitions/{WID}/publish-requests", json={})
live = api.get(f"/v1/workflows/definitions/{WID}")
check(
    "2 James saves and publishes the workflow on the mailbox",
    saved.status_code == 201 and published.status_code == 201 and live.json()["data"].get("stage") == "live",
    f"{saved.status_code} {published.status_code} {live.text[:300]}",
)


def runs() -> list[dict[str, Any]]:
    r = api.get("/v1/runs", params={"workflowId": WID, "pageSize": 100})
    assert r.status_code == 200, r.text[:200]
    return list(r.json()["data"]["data"])


# The worker's first pass on a new binding reads the mailbox to its end and starts nothing; mail after it starts runs.
# Mail already in the folder from earlier runs of this use case is that history.
time.sleep(float(os.environ.get("OPS_EMAIL_POLL_SECONDS", "3")) * 3)
check("3 mail already in the mailbox started no run", runs() == [], runs())

mid = f"<uc150-{RUN}@court.example>"
send(mid)
try:
    [run] = until("the run", lambda: runs() or None)
    detail = api.get(f"/v1/runs/{run['id']}").json()["data"]
    inp = detail["input"]
    check(
        "4 the email started one run with the sender, subject and the PDF as a Files id",
        inp["from"] == "registry@court.example"
        and "garnishment" in inp["subject"]
        and len(inp["attachments"]) == 1
        and inp["attachments"][0]["fileId"].startswith("fil_")
        and "contentBytes" not in json.dumps(inp),
        inp,
    )
    file_id = inp["attachments"][0]["fileId"]
    got = httpx.get(f"{FILES}/v1/files/{file_id}/content", headers=james, timeout=30)
    check(
        "5 the PDF is in Files as the team's file, byte for byte",
        got.status_code == 200 and got.content == PDF,
        got.status_code,
    )
    # The same message again, its Message-ID written with other brackets and domain case.
    send(f" uc150-{RUN}@COURT.example ")
    time.sleep(float(os.environ.get("OPS_EMAIL_POLL_SECONDS", "3")) * 3)
    check("6 a redelivery of the same message started no second run", len(runs()) == 1, runs())
except TimeoutError as e:
    check("4 the email started one run", False, str(e))
finally:
    api.post(f"/v1/workflows/definitions/{WID}/pause")
finish()
