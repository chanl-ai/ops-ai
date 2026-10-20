"""The mailbox demo on the shared stack, end to end, through the public API (`make demo-mailbox`).

A real email with a levy notice attached goes through local SMTP (GreenMail) to the team mailbox
intake@northfield.test. The worker reads it over IMAP through tools-service and the mail_intake workflow takes it: the
attachment is stored in Files, mail_document reads the debtors from it and starts a levy_case run per debtor (a matched
debtor waits on a 'Levy notice' Human Task), then waits for a person to acknowledge the document. The demo approves
that acknowledgement as Maya (an approver) and finds the reply in Mailpit. Each step prints PASS or FAIL with its
evidence; the exit status is the number of failures.

Every run sends a fresh message (its own Message-ID and subject suffix), so running it again stays green and never
meets the dedupe of an earlier message. The notice is read by whatever model the alias `default` serves: a real OpenAI
model on the shared stack (make up's DEMO_MODEL), the fake with its demo rules after `make demo-model MODEL=fake`.
"""

from __future__ import annotations

import os
import smtplib
import socket
import sys
import time
import uuid
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any

import httpx

from ops_identity import mint_service_token
from ops_identity.service_keys import dev_service_signer

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = Path(os.environ.get("OPS_RUN_DIR", ROOT / ".run"))
AGENTS = f"http://127.0.0.1:{os.environ.get('OPS_AGENTS_PORT', '8700')}"
PLATFORM = f"http://127.0.0.1:{os.environ.get('OPS_PLATFORM_PORT', '8710')}"
TOOLS = f"http://127.0.0.1:{os.environ.get('OPS_TOOLS_PORT', '8720')}"
FILES = f"http://127.0.0.1:{os.environ.get('OPS_FILES_PORT', '8750')}"
MODELS = f"http://127.0.0.1:{os.environ.get('OPS_MODELS_PORT', '8730')}"
FAKE_OPENAI = f"http://127.0.0.1:{os.environ.get('OPS_FAKE_OPENAI_PORT', '8746')}"
SMTP_PORT = int(os.environ.get("OPS_GREENMAIL_SMTP_PORT", "3025"))
MAILPIT = f"http://127.0.0.1:{os.environ.get('OPS_MAILPIT_HTTP_PORT', '8025')}"
MAILBOX = "intake@northfield.test"
TEAM = "team_ops"
PASSWORD = "northfield-demo"
JAMES, MAYA = "j.richardson@northfieldbank.com", "m.okafor@northfieldbank.com"
FIXTURES = ROOT / "services" / "agents-service" / "tests" / "fixtures" / "mailbox"
# LOW=1 sends a scan of the same notice, read through OCR, and raises the workspace review floor (the extractionFloor
# policy, Govern > Policies) to LOW_FLOOR for the run, putting it back after: OCR reads the clean scan above the default
# 0.8, so the floor, not the scan, is what sends the read to a person before any case opens.
LOW = os.environ.get("LOW") == "1"
NOTICE = FIXTURES / ("levy_notice_scan.pdf" if LOW else "levy_notice.pdf")
WAIT_S = float(os.environ.get("DEMO_WAIT_SECONDS", "120"))
LOW_FLOOR = 0.99
SECURITY_ADMIN = "s.adeyemi@northfieldbank.com"

FAILED: list[str] = []


def step(ok: bool, name: str, evidence: str) -> bool:
    if not ok:
        FAILED.append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {evidence}", flush=True)
    return ok


def up(url: str, seconds: float = 30.0) -> bool:
    """Whether `url` answers within `seconds`: a service restarted a moment ago is given time to come up."""
    end = time.monotonic() + seconds
    while True:
        try:
            if httpx.get(url, timeout=3).status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        if time.monotonic() > end:
            return False
        time.sleep(1)


def get(url: str, **kw: Any) -> httpx.Response:
    """A read, asked again once when the connection drops or times out: the first request after a service restarts can
    wait on its warm-up. Writes are never sent twice."""
    try:
        return httpx.get(url, **kw)
    except httpx.TransportError:
        time.sleep(2)
        return httpx.get(url, **kw)


def mail_pin() -> str | None:
    """Why the dev mail cannot be read, when tools-service dials this machine at an address it no longer has (the
    network changed since tools-service started; scripts/stack.sh records the address it pinned)."""
    pinned = RUN_DIR / "tools.pinned"
    if not pinned.exists():
        return None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("10.255.255.255", 1))
        now = s.getsockname()[0]
    was = pinned.read_text().strip()
    return None if was == now else f"tools-service dials the dev mail at {was}, this machine is now {now}"


def tcp(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def worker_alive() -> bool:
    pid = RUN_DIR / "worker.pid"
    if not pid.exists():
        return False
    try:
        os.kill(int(pid.read_text().strip()), 0)
    except (OSError, ValueError):
        return False
    return True


def sign_in(email: str) -> dict[str, str]:
    r = httpx.post(f"{PLATFORM}/v1/auth/sign-in", json={"email": email, "password": PASSWORD}, timeout=10)
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": TEAM}


def data(r: httpx.Response) -> Any:
    r.raise_for_status()
    return r.json()["data"]


def until(what: str, probe: Any, seconds: float = WAIT_S) -> Any:
    """`probe()` until it returns something truthy, or None after `seconds`."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        found = probe()
        if found:
            return found
        time.sleep(1.5)
    print(f"      (gave up waiting for {what} after {seconds:.0f}s)", flush=True)
    return None


def preflight() -> bool:
    checks = [
        ("platform-service", up(f"{PLATFORM}/v1/health")),
        ("agents-service", up(f"{AGENTS}/health")),
        ("tools-service", up(f"{TOOLS}/health")),
        ("files-service", up(f"{FILES}/health")),
        ("models-service", up(f"{MODELS}/health")),
        ("fake OpenAI", tcp(int(FAKE_OPENAI.rsplit(":", 1)[1]))),
        ("workflow worker", worker_alive()),
        ("GreenMail SMTP", tcp(SMTP_PORT)),
        ("Mailpit", up(f"{MAILPIT}/api/v1/info")),
    ]
    missing = [name for name, ok in checks if not ok]
    if missing:
        return step(False, "stack", f"down: {', '.join(missing)} (run `make up AUTH=platform`)")
    stale = mail_pin()
    return step(stale is None, "stack", f"{stale} (run `make restart SVC=tools`)" if stale else "all up")


def send(suffix: str, sender: str) -> str:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = MAILBOX
    msg["Subject"] = f"Levy notice {suffix}"
    msg["Message-ID"] = make_msgid(idstring=suffix, domain="court.example")
    msg.set_content("Please find the garnishment notice attached.")
    msg.add_attachment(NOTICE.read_bytes(), maintype="application", subtype="pdf", filename=f"levy-{suffix}.pdf")
    with smtplib.SMTP("127.0.0.1", SMTP_PORT, timeout=10) as smtp:
        smtp.send_message(msg)
    return str(msg["Subject"])


def served_by(run_id: str, step_id: str) -> str:
    """The model that served a step, from models-service's call log (read with a dev service token)."""
    token = mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id="team_ops")
    try:
        r = get(f"{MODELS}/v1/models/calls", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        calls = r.json()["data"]["items"]
    except (httpx.HTTPError, KeyError, ValueError):
        return "model: call log unreadable"
    for c in calls:
        if c.get("runId") == run_id and c.get("stepId") == step_id:
            return f"model {c['providerModel']} (alias {c['alias']} v{c['aliasVersion']}, {c['latencyMs']} ms)"
    return "model: no call logged for the step"


def run_detail(h: dict[str, str], run_id: str) -> dict[str, Any]:
    return data(get(f"{AGENTS}/v1/runs/{run_id}", headers=h, timeout=10))


def out_of(run: dict[str, Any], node: str) -> Any:
    return next((s.get("output") for s in run.get("steps", []) if s.get("nodeId") == node), None)


def floor_set(value: float | None) -> float | None:
    """Sets the workspace review floor as the Security team's admin and returns the value it had."""
    r = httpx.post(f"{PLATFORM}/v1/auth/sign-in", json={"email": SECURITY_ADMIN, "password": PASSWORD}, timeout=10)
    r.raise_for_status()
    h = {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": "team_security"}
    was = data(get(f"{PLATFORM}/v1/policies/extractionFloor", headers=h, timeout=10)).get("value")
    data(httpx.put(f"{PLATFORM}/v1/policies/extractionFloor", json={"value": value}, headers=h, timeout=10))
    return was


def main() -> int:
    if not preflight():
        return len(FAILED)
    if not LOW:
        return run()
    was = floor_set(LOW_FLOOR)
    print(f"      review floor {LOW_FLOOR} for this run (was {was})", flush=True)
    try:
        return run()
    finally:
        floor_set(was)


def run() -> int:
    james, maya = sign_in(JAMES), sign_in(MAYA)
    suffix = uuid.uuid4().hex[:8]
    sender = f"clerk+{suffix}@court.example"
    started = time.time()
    subject = send(suffix, sender)
    print(f"      sent '{subject}' from {sender} to {MAILBOX}", flush=True)

    def intake_run() -> dict[str, Any] | None:
        listed = get(f"{AGENTS}/v1/runs", params={"workflowId": "mail_intake"}, headers=james, timeout=10)
        rows = data(listed)["data"]
        for row in rows[:20]:
            run = run_detail(james, row["id"])
            if suffix in str(run.get("input")):
                return run
        return None

    intake = until("the mail_intake run", intake_run)
    if not step(intake is not None, "run started", f"mail_intake {intake['id']}" if intake else "no run for it"):
        return len(FAILED)
    attachments = (intake.get("input") or {}).get("attachments") or []
    file_id = attachments[0]["fileId"] if attachments else None
    stored = file_id and get(f"{FILES}/v1/files/{file_id}", headers=james, timeout=10).status_code == 200
    found = f"{file_id} ({attachments[0]['name']})" if stored else f"attachments: {attachments}"
    step(bool(stored), "attachment in Files", found)

    def document_run() -> dict[str, Any] | None:
        settled = run_detail(james, intake["id"])
        started_runs = (out_of(settled, "each") or {}).get("runs") or []
        return run_detail(james, started_runs[0]["runId"]) if started_runs else None

    doc = until("the mail_document run", document_run)
    if not step(doc is not None, "document run", f"mail_document {doc['id']}" if doc else "no child run started"):
        return len(FAILED)

    def read_out() -> Any:
        return out_of(run_detail(james, doc["id"]), "read")

    read = until("the read step", read_out)
    records = (read or {}).get("records") or []
    names = [r["values"].get("name") for r in records]
    low = (read or {}).get("needsReview") or []
    read_line = f"{len(records)} debtor(s): {', '.join(map(str, names))}; below the floor: {len(low)}; "
    # The read's model call is logged under the extraction that files-service ran for the step (c-235).
    read_line += served_by(str((read or {}).get("extractionId") or ""), "extract")
    step(bool(records) and (bool(low) if LOW else True), "fields read", read_line)

    def read_as() -> dict[str, Any] | None:
        # What the Files list and file page show: the read mail_document's Save data on file step recorded (c-378).
        detail: dict[str, Any] = data(get(f"{FILES}/v1/files/{file_id}", headers=james, timeout=10))
        recorded: dict[str, Any] | None = detail.get("data") or None
        return recorded

    saved: dict[str, Any] = until("the file's read", read_as) or {}
    shown = f"{saved.get('typeName')} v{saved.get('version')} · {saved.get('path')}" if saved else "Not read"
    step(saved.get("typeName") == "Levy notice" and saved.get("version") == 1, "file read as", shown)

    def paused_at(*nodes: str) -> dict[str, Any] | None:
        run = run_detail(james, doc["id"])
        waiting = run.get("waiting") or {}
        return run if run.get("status") == "waiting" and waiting.get("node") in nodes else None

    def check_or_cases() -> dict[str, Any] | None:
        run = run_detail(james, doc["id"])
        return run if (run.get("waiting") or {}).get("node") == "check" or out_of(run, "open") else None

    # A read below the floor stops at "Check the debtors read from the document" before any case opens.
    first = until("the check or the cases", check_or_cases) or {}
    if (first.get("waiting") or {}).get("node") == "check":
        step(
            out_of(first, "open") is None,
            "check Human Task",
            f"{doc['id']} waits at 'check' with {len(low)} field(s) below the floor; no case opened yet",
        )
        check = {"decision": "approved", "reason": "Demo: the read is right"}
        data(httpx.post(f"{AGENTS}/reviews/{doc['id']}/decision", json=check, headers=maya, timeout=20))
        print(f"      check approved as {MAYA}", flush=True)
    elif LOW:
        step(False, "check Human Task", "the scan's read went straight to the cases")

    def opened() -> Any:
        return out_of(run_detail(james, doc["id"]), "open")

    cases = until("the levy cases", opened)
    case_ids = [r["runId"] for r in (cases or {}).get("runs", [])]

    def settled_cases() -> list[dict[str, Any]] | None:
        rows = [run_detail(james, run_id) for run_id in case_ids]
        return rows if rows and all(r["status"] in ("waiting", "succeeded", "failed") for r in rows) else None

    # One levy_case run per debtor: a debtor matched to a customer waits for a person on the 'Levy notice' Human Task
    # (hold the account or flag the customer); one with no match ends not_matched.
    levy = until("the levy cases to settle", settled_cases) or []
    lines = [
        f"{r['input']['record']['name']} -> "
        + ("Human Task 'Levy notice'" if (r.get("waiting") or {}).get("node") == "review" else str(r.get("outcome")))
        for r in levy
    ]
    reviewed = sum(1 for r in levy if (r.get("waiting") or {}).get("node") == "review")
    step(len(levy) == len(records) and reviewed > 0, "levy cases", f"{len(levy)} run(s): {'; '.join(lines)}")

    # The 'Levy notice' rows on Human Tasks name the debtor, the amount and the account's currency.
    listed = data(get(f"{AGENTS}/reviews", params={"view": "open", "pageSize": 100}, headers=maya, timeout=10))
    waiting_ids = {r["id"] for r in levy if (r.get("waiting") or {}).get("node") == "review"}
    rows = [x for x in listed["data"] if str(x["id"]).split(":", 1)[0] in waiting_ids]
    shown = [f"{x['customer']} {x['amount']} {x['currency']}" for x in rows]
    step(
        len(rows) == reviewed and all(x["customer"] and x["amount"] is not None for x in rows),
        "Human Task rows",
        "; ".join(shown) or "no open row for the levy cases",
    )

    # Each levy_case run opens a case for its debtor (Open case step `case`, or `case_unmatched`), shown on Cases.
    opened_cases: list[str] = []
    for r in levy:
        case_id = ((out_of(r, "case") or out_of(r, "case_unmatched")) or {}).get("caseId")
        got = get(f"{AGENTS}/v1/cases/{case_id}", headers=james, timeout=10) if case_id else None
        if got is not None and got.status_code == 200:
            case = got.json()["data"]
            opened_cases.append(f"{case['subject']} [{case.get('customerId') or 'no customer'}, {case['priority']}]")
    step(
        len(opened_cases) == len(levy) > 0,
        "case opened",
        "; ".join(opened_cases) or "no case on the levy runs",
    )

    paused = until("the Human Task", lambda: paused_at("ack"))
    waits = f"{doc['id']} waits at 'ack'" if paused else "none opened"
    if not step(paused is not None, "acknowledge Human Task", waits):
        return len(FAILED)
    decided = httpx.post(
        f"{AGENTS}/reviews/{doc['id']}/decision",
        json={"decision": "approved", "reason": "Demo: acknowledge the notice"},
        headers=maya,
        timeout=20,
    )
    step(decided.status_code == 200, "acknowledged", f"as {MAYA}" if decided.status_code == 200 else decided.text[:300])

    def reply() -> dict[str, Any] | None:
        r = get(f"{MAILPIT}/api/v1/search", params={"query": f'to:"{sender}"'}, timeout=10)
        found = [m for m in r.json().get("messages", []) if suffix in str(m.get("Subject"))]
        return found[0] if found else None

    sent = until("the reply in Mailpit", reply)
    step(
        sent is not None,
        "reply in Mailpit",
        f"'{sent['Subject']}' from {sent['From']['Address']} to {sender}" if sent else f"none to {sender}",
    )
    print(f"      {time.time() - started:.0f}s; console: http://localhost:3016/workflows/runs/{doc['id']}", flush=True)
    return len(FAILED)


if __name__ == "__main__":
    sys.exit(main())
