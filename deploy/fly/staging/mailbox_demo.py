"""Prepares a deployed Ops AI for the mailbox demo through its public origin, as its people would through the console,
and walks the demo against a test mailbox (docs/console/mailbox-demo.md, "On Fly staging").

    python deploy/fly/staging/mailbox_demo.py seed --origin https://<your-app>-web.fly.dev \\
        --admin-env ~/.config/ops-ai/staging-admin.env --people ~/.config/ops-ai/staging-demo-people.env \\
        --bank https://<your-app>-bank.fly.dev --bank-env ~/.config/ops-ai/staging-bank.env
    python deploy/fly/staging/mailbox_demo.py walk --origin <origin> --admin-env ... --people ... \\
        --mailbox intake@demo.test --imap mail.demo.test:3993 --smtp smtp.demo.test:1025 --send-smtp 127.0.0.1:13025 \\
        --read-mailpit http://127.0.0.1:18025

`seed` is re-runnable; each step says what it made or found:
  1. a second person, an approver in the Security team, for the two-person publish reviews (credentials are
     generated once into --people, mode 600, and never printed);
  2. egress: Gmail's, Microsoft 365's and Ethereal's IMAP and SMTP, Microsoft Graph and its sign-in, and the bank
     stand-in's host (`egress` runs this step alone);
  3. the bank stand-in as a tool module, from its OpenAPI document, with its key and webhook secret in Secrets;
  4. the document types the levy workflows read (services/documents-service/scripts/seed_document_types.py);
  5. the mail workflows (levy_case, mail_document, mail_intake, levy_read_one, levy_mail), owned by Security,
     published and approved. --mailbox points the Email received triggers at a connected mailbox.

`walk` connects a test mailbox the way a person does on Channels > Email, points mail_intake at it, emails the levy
notice to it, and checks each step through the API: the run, the attachment in Files, the read, the levy cases, the
'Levy notice' Human Tasks, the acknowledgement and the reply in the sender's inbox. It prints PASS or FAIL per step and
exits with the number of failures. No model is named here: the reads go to whatever the `default` alias serves.
"""

from __future__ import annotations

import argparse
import asyncio
import imaplib
import json
import os
import secrets
import smtplib
import ssl
import sys
import time
import uuid
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import certifi
import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "tools-service" / "scripts"))
sys.path.insert(0, str(ROOT / "services" / "documents-service" / "scripts"))
from reimport_bank_module import ensure_module, ensure_secret, reimport  # noqa: E402
from seed_document_types import seed as seed_document_types  # noqa: E402

SECURITY = "team_security"
WORKFLOWS = ("levy_case", "mail_document", "mail_intake", "levy_read_one", "levy_mail")
EMAIL_TRIGGERED = ("mail_intake", "levy_mail")
# Gmail (IMAP 993, SMTP 587 with STARTTLS), Microsoft 365 (IMAP and SMTP, or Graph and its sign-in), and Ethereal,
# staging's test mailbox (IMAP 993, SMTP 587 with STARTTLS). The allow-list names hosts; the port is the mailbox's.
MAIL_HOSTS = (
    "imap.gmail.com",
    "smtp.gmail.com",
    "imap.ethereal.email",
    "smtp.ethereal.email",
    "outlook.office365.com",
    "smtp.office365.com",
    "graph.microsoft.com",
    "login.microsoftonline.com",
)
NOTICE = ROOT / "services" / "agents-service" / "tests" / "fixtures" / "mailbox" / "levy_notice.pdf"
WAIT_S = float(os.environ.get("DEMO_WAIT_SECONDS", "180"))
FAILED: list[str] = []


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return dict(line.strip().split("=", 1) for line in path.read_text().splitlines() if "=" in line)


def write_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))


def data(r: httpx.Response) -> Any:
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400 or not body.get("success"):
        raise SystemExit(f"{r.request.method} {r.request.url.path} -> {r.status_code} {r.text[:400]}")
    return body["data"]


def sign_in(origin: str, email: str, password: str) -> dict[str, Any]:
    """A session; asked again a few times, since the first request after a quiet spell can meet a closed pool."""
    for _ in range(4):
        r = httpx.post(
            f"{origin}/api/platform/v1/auth/sign-in", json={"email": email, "password": password}, timeout=30
        )
        if r.status_code == 200:
            return dict(r.json()["data"])
        time.sleep(1.5)
    raise SystemExit(f"sign-in as {email} failed: {r.status_code} {r.text[:200]}")


def bearer(session: dict[str, Any], team: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['token']}", "X-Team-Id": team}


class Demo:
    def __init__(self, origin: str, admin_env: Path, people: Path) -> None:
        self.origin = origin.rstrip("/")
        admin = read_env(admin_env)
        self.admin_email = admin["OPS_BOOTSTRAP_ADMIN_EMAIL"]
        self.admin = sign_in(self.origin, self.admin_email, admin["OPS_BOOTSTRAP_ADMIN_PASSWORD"])
        self.people_file = people
        # The demo runs in the first team, the one the install made (Security). tools-service knows teams from its
        # own fixed list, not platform-service's, so a team made on the Teams page is not one it can name yet.
        self.ops = SECURITY
        self.approver = self.second_person()

    def url(self, service: str, path: str) -> str:
        return f"{self.origin}/api/{service}{path}"

    def as_admin(self, team: str | None = None) -> dict[str, str]:
        return bearer(self.admin, team or self.ops)

    def as_approver(self, team: str | None = None) -> dict[str, str]:
        return bearer(self.approver, team or self.ops)

    def second_person(self) -> dict[str, Any]:
        """An approver in the demo team: publish reviews need a second person by default."""
        known = read_env(self.people_file)
        if known.get("APPROVER_EMAIL"):
            session = sign_in(self.origin, known["APPROVER_EMAIL"], known["APPROVER_PASSWORD"])
        else:
            domain = self.admin_email.split("@", 1)[1]
            email = f"approver@{domain}"
            password = secrets.token_urlsafe(18)
            invited = data(
                httpx.post(
                    self.url("platform", "/v1/settings/members/invite"),
                    json={"emails": [email], "role": "approver"},
                    headers=bearer(self.admin, SECURITY),
                    timeout=30,
                )
            )
            token = invited["invites"][0]["token"]
            data(
                httpx.post(
                    self.url("platform", f"/v1/invites/{token}/accept"),
                    json={"name": "Demo Approver", "password": password},
                    timeout=30,
                )
            )
            write_env(self.people_file, {**known, "APPROVER_EMAIL": email, "APPROVER_PASSWORD": password})
            print(f"second person: {email}, approver in Security (credentials in {self.people_file})")
            session = sign_in(self.origin, email, password)
        return session

    def egress(self, hosts: list[str], ranges: list[str]) -> None:
        h = bearer(self.admin, SECURITY)
        listed = data(httpx.get(self.url("tools", "/v1/egress"), headers=h, timeout=30))
        for kind, wanted in (("hosts", hosts), ("ranges", ranges)):
            have = {
                str(x.get("host") or x.get("range") or x.get("cidr") or x.get("value")) for x in listed.get(kind) or []
            }
            for value in wanted:
                if value in have:
                    continue
                data(
                    httpx.post(
                        self.url("tools", f"/v1/egress/{kind}"),
                        json={"value": value, "note": "Mailbox demo (deploy/fly/staging/mailbox_demo.py)"},
                        headers=h,
                        timeout=30,
                    )
                )
                print(f"egress: allowed {value}")
        print(f"egress: {', '.join(hosts + ranges)} allowed")

    async def bank(self, bank_url: str, bank_env: dict[str, str]) -> None:
        host = urlparse(bank_url).hostname or bank_url
        async with (
            httpx.AsyncClient(base_url=self.url("tools", ""), headers=self.as_admin(SECURITY), timeout=60) as keeper,
            httpx.AsyncClient(base_url=self.url("tools", ""), headers=self.as_admin(), timeout=60) as api,
            httpx.AsyncClient(
                base_url=self.url("agents", ""), headers=self.as_approver(SECURITY), timeout=60
            ) as approver,
        ):
            print(f"BANK_API_KEY: {await ensure_secret(keeper, 'BANK_API_KEY', bank_env['FAKE_BANK_KEY'])}")
            webhook = bank_env["FAKE_BANK_WEBHOOK_SECRET"]
            print(f"LEVY_WEBHOOK_SECRET: {await ensure_secret(keeper, 'LEVY_WEBHOOK_SECRET', webhook)}")
            module_id, created = await ensure_module(api, host)
            print(f"bank module {module_id}: {'imported' if created else 'found'} from https://{host}/openapi.json")
            module = await reimport(api, module_id, host=host, hold_team=self.ops, approver=approver)
            current = next(v for v in module["versions"] if v["version"] == module["version"])
            print(
                f"bank module: {len(module['operations'])} operations, version {module['version']} {current['status']}"
            )

    def document_types(self) -> None:
        h = self.as_admin()
        with (
            httpx.Client(base_url=self.url("documents", ""), headers=h, timeout=120) as documents,
            httpx.Client(base_url=self.url("files", ""), headers=h, timeout=120) as files,
        ):
            print(f"document types: {seed_document_types(documents, files)}")

    def workflows(self, mailbox: str | None, levy_mailbox: str | None = None) -> None:
        """Each workflow saved and published. An Email received trigger publishes only on a connected mailbox, so
        mail_intake (on `mailbox`) and levy_mail (on `levy_mailbox`) stay drafts until one is named."""
        seeded = {
            w["id"]: w for w in json.loads((ROOT / "services/agents-service/seed/engine_workflows.json").read_text())
        }
        reads = {"mail_intake": mailbox, "levy_mail": levy_mailbox}
        for wid in WORKFLOWS:
            d = {k: v for k, v in seeded[wid].items() if k != "teamId"}
            if wid in reads:
                if not reads[wid]:
                    self.save(wid, d)
                    print(f"workflow {wid}: saved as a draft; pick a mailbox in its Email received trigger to publish")
                    continue
                for n in d["nodes"]:
                    if n["type"] == "ops.trigger.email":
                        n["parameters"]["mailbox"] = reads[wid]
            self.publish(wid, d)

    def save(self, wid: str, definition: dict[str, Any]) -> dict[str, Any]:
        return dict(
            data(
                httpx.post(
                    self.url("agents", "/v1/workflows/definitions"),
                    json={"definition": definition},
                    headers=self.as_admin(),
                    timeout=60,
                )
            )
        )

    def publish(self, wid: str, definition: dict[str, Any]) -> None:
        h = self.as_admin()
        saved = self.save(wid, definition)
        view = data(httpx.get(self.url("agents", f"/v1/workflows/definitions/{wid}"), headers=h, timeout=30))
        if view.get("liveVersion") == saved["version"]:
            print(f"workflow {wid}: v{saved['version']} already live")
            return
        asked = data(
            httpx.post(
                self.url("agents", f"/v1/workflows/definitions/{wid}/publish-requests"),
                json={"version": saved["version"]},
                headers=h,
                timeout=60,
            )
        )
        if asked.get("status") == "pending":
            asked = data(
                httpx.post(
                    self.url("agents", f"/v1/publish-requests/{asked['id']}/decision"),
                    json={"decision": "approved"},
                    headers=self.as_approver(),
                    timeout=60,
                )
            )
        live = data(httpx.get(self.url("agents", f"/v1/workflows/definitions/{wid}"), headers=h, timeout=30))
        print(f"workflow {wid}: v{saved['version']} {asked.get('status')}, live v{live.get('liveVersion')}")


def step(ok: bool, name: str, evidence: str) -> bool:
    if not ok:
        FAILED.append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {evidence}", flush=True)
    return ok


def until(what: str, probe: Any, seconds: float = WAIT_S) -> Any:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            found = probe()
        except (httpx.HTTPError, SystemExit):
            found = None
        if found:
            return found
        time.sleep(2)
    print(f"      (gave up waiting for {what} after {seconds:.0f}s)", flush=True)
    return None


def tls_context() -> ssl.SSLContext:
    """A verifying TLS context with certifi's CA bundle: the python.org macOS build ships with no CA store, so the
    default context cannot verify any provider until its Install Certificates step runs."""
    return ssl.create_default_context(cafile=certifi.where())


def hostport(value: str) -> tuple[str, int]:
    host, port = value.rsplit(":", 1)
    return host, int(port)


def walk(demo: Demo, a: argparse.Namespace) -> int:
    ops, admin = demo.ops, demo.as_admin()
    imap_host, imap_port = hostport(a.imap)
    smtp_host, smtp_port = hostport(a.smtp)
    # Settings > Secrets: the mailbox password, for the demo team only.
    r = httpx.post(
        demo.url("tools", "/v1/secrets"),
        json={"name": "DEMO_MAILBOX_PASSWORD", "value": a.mailbox_password, "teams": [ops]},
        headers=demo.as_admin(SECURITY),
        timeout=30,
    )
    step(r.status_code in (201, 409), "mailbox secret", f"DEMO_MAILBOX_PASSWORD {r.status_code}")
    # Settings > Egress: the mailbox's servers.
    demo.egress([imap_host, smtp_host], [])
    # Channels > Email > Connect mailbox, then Test connection.
    boxes = data(httpx.get(demo.url("agents", "/v1/channels/mailboxes"), headers=admin, timeout=30))
    box = next((b for b in boxes if b["address"] == a.mailbox), None)
    if box is None:
        box = data(
            httpx.post(
                demo.url("agents", "/v1/channels/mailboxes"),
                json={
                    "name": "Demo intake",
                    "address": a.mailbox,
                    "provider": "imap",
                    "imapHost": imap_host,
                    "imapPort": imap_port,
                    "imapTls": True,
                    "passwordSecret": "DEMO_MAILBOX_PASSWORD",
                    "sender": "smtp",
                    "fromAddress": a.mailbox,
                    "smtpHost": smtp_host,
                    "smtpPort": smtp_port,
                    "smtpStarttls": True,
                    "senderSecret": "DEMO_MAILBOX_PASSWORD",
                },
                headers=admin,
                timeout=30,
            )
        )
    tested = httpx.post(demo.url("agents", f"/v1/channels/mailboxes/{box['id']}/test"), headers=admin, timeout=90)
    result = tested.json().get("data") or {} if tested.status_code == 200 else {}
    steps = ", ".join(f"{x['title']}: {x['state']}" for x in result.get("steps") or [])
    step(bool(result.get("ok")), "mailbox connected", f"{box['id']} {a.mailbox}: {steps or tested.text[:300]}")
    # The Email received trigger picks the mailbox; the change is published and approved.
    demo.workflows(a.mailbox)

    suffix = uuid.uuid4().hex[:8]
    sender = f"clerk+{suffix}@court.example"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, a.mailbox, f"Levy notice {suffix}"
    msg["Message-ID"] = make_msgid(idstring=suffix, domain="court.example")
    msg.set_content("Please find the garnishment notice attached.")
    msg.add_attachment(NOTICE.read_bytes(), maintype="application", subtype="pdf", filename=f"levy-{suffix}.pdf")
    send_host, send_port = hostport(a.send_smtp)
    with smtplib.SMTP(send_host, send_port, timeout=20) as smtp:
        if a.send_user:
            # A real provider (Ethereal) takes mail only over STARTTLS from a signed-in account.
            smtp.starttls(context=tls_context())
            smtp.login(a.send_user, a.mailbox_password)
        smtp.send_message(msg)
    print(f"      sent '{msg['Subject']}' from {sender} to {a.mailbox}", flush=True)
    started = time.time()

    def run(run_id: str) -> dict[str, Any]:
        return dict(data(httpx.get(demo.url("agents", f"/v1/runs/{run_id}"), headers=admin, timeout=30)))

    def out_of(r: dict[str, Any], node: str) -> Any:
        return next((s.get("output") for s in r.get("steps", []) if s.get("nodeId") == node), None)

    def intake_run() -> dict[str, Any] | None:
        rows = data(
            httpx.get(demo.url("agents", "/v1/runs"), params={"workflowId": "mail_intake"}, headers=admin, timeout=30)
        )["data"]
        for row in rows[:20]:
            got = run(row["id"])
            if suffix in str(got.get("input")):
                return got
        return None

    intake = until("the mail_intake run", intake_run)
    if not step(intake is not None, "run started", f"mail_intake {intake['id']}" if intake else "no run"):
        return len(FAILED)
    attachments = (intake.get("input") or {}).get("attachments") or []
    file_id = attachments[0]["fileId"] if attachments else None
    stored = (
        bool(file_id)
        and httpx.get(demo.url("files", f"/v1/files/{file_id}"), headers=admin, timeout=30).status_code == 200
    )
    step(stored, "attachment in Files", f"{file_id}" if stored else f"attachments: {attachments}")

    def document_run() -> dict[str, Any] | None:
        started_runs = (out_of(run(intake["id"]), "each") or {}).get("runs") or []
        return run(started_runs[0]["runId"]) if started_runs else None

    doc = until("the mail_document run", document_run)
    if not step(doc is not None, "document run", f"mail_document {doc['id']}" if doc else "no child run"):
        return len(FAILED)
    read = until("the read step", lambda: out_of(run(doc["id"]), "read"))
    records = (read or {}).get("records") or []
    step(bool(records), "fields read", f"{len(records)} debtor(s): {[r['values'].get('name') for r in records]}")

    def check_or_cases() -> dict[str, Any] | None:
        got = run(doc["id"])
        return got if (got.get("waiting") or {}).get("node") == "check" or out_of(got, "open") else None

    first = until("the check or the cases", check_or_cases) or {}
    if (first.get("waiting") or {}).get("node") == "check":
        decided = httpx.post(
            demo.url("agents", f"/reviews/{doc['id']}/decision"),
            json={"decision": "approved", "reason": "Demo: the read is right"},
            headers=demo.as_approver(),
            timeout=30,
        )
        step(decided.status_code == 200, "check Human Task", f"approved: {decided.status_code}")
    cases = until("the levy cases", lambda: out_of(run(doc["id"]), "open"))
    case_runs = [r["runId"] for r in (cases or {}).get("runs", [])]

    def settled() -> list[dict[str, Any]] | None:
        rows = [run(x) for x in case_runs]
        return rows if rows and all(r["status"] in ("waiting", "succeeded", "failed") for r in rows) else None

    levy = until("the levy cases to settle", settled) or []
    lines = [
        f"{r['input']['record']['name']} -> {(r.get('waiting') or {}).get('node') or r.get('outcome')}" for r in levy
    ]
    step(bool(levy) and all(r["status"] != "failed" for r in levy), "levy case runs", "; ".join(lines) or "none")
    opened = []
    for r in levy:
        case_id = ((out_of(r, "case") or out_of(r, "case_unmatched")) or {}).get("caseId")
        got = httpx.get(demo.url("agents", f"/v1/cases/{case_id}"), headers=admin, timeout=30) if case_id else None
        if got is not None and got.status_code == 200:
            c = got.json()["data"]
            opened.append(f"{c['subject']} [{c.get('customerId') or 'no customer'}]")
    step(len(opened) == len(levy) > 0, "cases opened", "; ".join(opened) or "none")
    listed = data(
        httpx.get(demo.url("agents", "/reviews"), params={"view": "open", "pageSize": 100}, headers=admin, timeout=30)
    )
    waiting_ids = {r["id"] for r in levy if (r.get("waiting") or {}).get("node") == "review"}
    rows = [x for x in listed["data"] if str(x["id"]).split(":", 1)[0] in waiting_ids]
    step(
        bool(rows),
        "Human Tasks",
        "; ".join(f"{x.get('title')}: {x.get('customer')} {x.get('amount')}" for x in rows) or "none",
    )

    def at_ack() -> dict[str, Any] | None:
        got = run(doc["id"])
        return got if (got.get("waiting") or {}).get("node") == "ack" else None

    paused = until("the acknowledge task", at_ack)
    if not step(paused is not None, "acknowledge Human Task", f"{doc['id']} waits at 'ack'" if paused else "none"):
        return len(FAILED)
    decided = httpx.post(
        demo.url("agents", f"/reviews/{doc['id']}/decision"),
        json={"decision": "approved", "reason": "Demo: acknowledge the notice"},
        headers=admin,
        timeout=30,
    )
    step(
        decided.status_code == 200, "acknowledged", f"as {demo.admin_email}: {decided.status_code} {decided.text[:200]}"
    )

    def reply() -> str | None:
        if a.read_imap:
            return imap_reply(a, sender, suffix)
        r = httpx.get(f"{a.read_mailpit}/api/v1/search", params={"query": f'to:"{sender}"'}, timeout=30)
        found = [m for m in r.json().get("messages", []) if suffix in str(m.get("Subject"))]
        return f"'{found[0]['Subject']}' from {found[0]['From']['Address']} to {sender}" if found else None

    sent = until("the reply", reply)
    step(sent is not None, "reply sent", sent or f"none to {sender}")
    print(f"      {time.time() - started:.0f}s from send to reply; run {doc['id']}", flush=True)
    return len(FAILED)


def imap_reply(a: argparse.Namespace, sender: str, suffix: str) -> str | None:
    """The reply in the mailbox itself, over IMAP with TLS: a provider that keeps what an account sends (Ethereal
    captures every message its SMTP accepts) holds it in some folder, so every selectable folder is searched."""
    host, port = hostport(a.read_imap)
    with imaplib.IMAP4_SSL(host, port, ssl_context=tls_context(), timeout=30) as box:
        box.login(a.mailbox, a.mailbox_password)
        _, folders = box.list()
        for line in folders or []:
            text = line.decode() if isinstance(line, bytes) else str(line)
            if "\\Noselect" in text:
                continue
            name = text.rsplit(' "', 1)[-1].rstrip('"') if text.endswith('"') else text.rsplit(" ", 1)[-1]
            if box.select(f'"{name}"', readonly=True)[0] != "OK":
                continue
            _, ids = box.search(None, "TO", f'"{sender}"', "SUBJECT", f'"{suffix}"')
            for num in (ids[0] or b"").split():
                _, parts = box.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                head = message_from_bytes(bytes(parts[0][1])) if parts and isinstance(parts[0], tuple) else None
                if head is not None:
                    return f"'{head['Subject']}' from {head['From']} to {sender} (IMAP folder {name})"
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("seed", "egress", "walk"):
        p = sub.add_parser(name)
        p.add_argument("--origin", required=True)
        p.add_argument("--admin-env", type=Path, required=True, help="OPS_BOOTSTRAP_ADMIN_EMAIL and _PASSWORD")
        p.add_argument("--people", type=Path, required=True, help="where the second person's credentials are kept")
        p.add_argument("--mailbox", help="the connected mailbox mail_intake reads")
        p.add_argument("--levy-mailbox", help="the connected mailbox levy_mail reads")
    seed = sub.choices["seed"]
    seed.add_argument("--bank", required=True, help="the bank stand-in's https origin")
    seed.add_argument("--bank-env", type=Path, required=True, help="FAKE_BANK_KEY and FAKE_BANK_WEBHOOK_SECRET")
    seed.add_argument("--egress-range", action="append", default=[], help="a private range to allow (local proof)")
    w = sub.choices["walk"]
    w.add_argument("--imap", required=True, help="host:port the services read the mailbox at")
    w.add_argument("--smtp", required=True, help="host:port the services send replies through")
    w.add_argument("--send-smtp", required=True, help="host:port this machine sends the notice through")
    found = w.add_mutually_exclusive_group(required=True)
    found.add_argument("--read-mailpit", help="the reply sender's Mailpit API, where the reply is found")
    found.add_argument("--read-imap", help="host:port of the mailbox's IMAP over TLS, where the reply is found")
    w.add_argument("--send-user", help="sign in to --send-smtp as this account, over STARTTLS")
    w.add_argument(
        "--mailbox-password",
        default=os.environ.get("DEMO_MAILBOX_PASSWORD", "greenmail-any"),
        help="the mailbox's password; default the DEMO_MAILBOX_PASSWORD environment variable, so it is never typed",
    )
    a = ap.parse_args()
    demo = Demo(a.origin, a.admin_env.expanduser(), a.people.expanduser())
    if a.cmd == "egress":
        demo.egress(list(MAIL_HOSTS), [])
    elif a.cmd == "seed":
        bank_host = urlparse(a.bank).hostname or a.bank
        demo.egress([*MAIL_HOSTS, bank_host], a.egress_range)
        asyncio.run(demo.bank(a.bank, read_env(a.bank_env.expanduser())))
        demo.document_types()
        demo.workflows(a.mailbox, a.levy_mailbox)
    else:
        sys.exit(walk(demo, a))


if __name__ == "__main__":
    main()
