"""Prepares a deployed Ops AI for the mailbox demo through its public origin, as its people would through the console,
and walks the demo against a test mailbox (docs/console/mailbox-demo.md, "On Fly staging").

    python deploy/fly/staging/mailbox_demo.py seed --origin https://<your-app>-one.fly.dev \\
        --admin-env ~/.config/ops-ai/staging-admin.env --people ~/.config/ops-ai/staging-demo-people.env \\
        --bank https://<your-app>-bank.fly.dev --bank-env ~/.config/ops-ai/staging-bank.env
    python deploy/fly/staging/mailbox_demo.py walk --origin <origin> --admin-env ... --people ... \\
        --team <team id> --intake-workflow <the team's Email received workflow> \\
        --mailbox intake@demo.test --imap mail.demo.test:3993 --smtp smtp.demo.test:1025 --send-smtp 127.0.0.1:13025 \\
        --read-mailpit http://127.0.0.1:18025 --bank-env ~/.config/ops-ai/staging-bank.env

`seed` is re-runnable; each step says what it made or found:
  1. a second person, an approver in the Security team, for the two-person publish reviews (credentials are
     generated once into --people, mode 600, and never printed);
  2. egress: Gmail's, Microsoft 365's and Ethereal's IMAP and SMTP, Microsoft Graph and its sign-in, and the bank
     stand-in's host (`egress` runs this step alone);
  3. the bank stand-in as a tool module, from its OpenAPI document, with its key and webhook secret in Secrets;
  4. the document types the levy workflows read (services/documents-service/scripts/seed_document_types.py);
  5. the mail workflows (levy_case, mail_document, mail_intake, levy_read_one, levy_mail), owned by Security,
     published and approved. --mailbox points the Email received triggers at a connected mailbox.

`walk` sets the mailbox up in --team the way a person does (the password a Secrets-page secret the team may use, the
mailbox's hosts on the egress list, Channels > Email > Connect mailbox and Test connection, the team's Email received
workflow pointed at it and published by a second person). It is re-runnable and is the setup step for any team; it
stops when the address is connected in another team, since a workspace connects an address once. Then it emails the
levy notice to the mailbox (--upload starts the document run from the uploaded notice instead, and needs no mailbox
password) and checks each step through the API: the run, the attachment in Files, the read, a case per debtor, each
matched debtor's hold approved and placed at the bank, the unmatched debtor's case with no customer, the
acknowledgement and the reply. It prints PASS or FAIL per step and exits with the number of failures. No model is
named here: the reads go to whatever the `extract` alias, or else `default`, serves.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
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
sys.path.insert(0, str(ROOT / "scripts" / "demo"))
import seed_demo_team as demo_seed  # noqa: E402
from reimport_bank_module import ensure_module, ensure_secret, reimport  # noqa: E402
from seed_demo_team import Refused, Session, decide, join_team, service_urls  # noqa: E402
from seed_demo_team import sign_in as person  # noqa: E402
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
    def __init__(self, origin: str, admin_env: Path, people: Path, team: str = SECURITY) -> None:
        self.origin = origin.rstrip("/")
        admin = read_env(admin_env)
        self.admin_email = admin["OPS_BOOTSTRAP_ADMIN_EMAIL"]
        self.admin_password = admin["OPS_BOOTSTRAP_ADMIN_PASSWORD"]
        self.admin = sign_in(self.origin, self.admin_email, self.admin_password)
        self.people_file = people
        # The team the demo runs in: Security, the install's first team, unless --team names another. The bank module,
        # the egress list and Secrets stay in Security either way.
        self.ops = team
        self.approver = self.second_person()
        if team != SECURITY:
            # The second person decides the team's publish reviews, so they join it as an approver, as a workspace
            # admin arranges; their session is renewed so it carries the team.
            known = read_env(self.people_file)
            join_team(self.person("admin"), self.person("approver"), team, "approver")
            self.approver = sign_in(self.origin, known["APPROVER_EMAIL"], known["APPROVER_PASSWORD"])

    def person(self, who: str) -> Session:
        """A signed-in person acting in the demo team, for the calls shared with scripts/demo/seed_demo_team.py
        (upload, decide); a step-up asks for the password again, so it is kept on the session."""
        if who == "admin":
            email, password = self.admin_email, self.admin_password
        else:
            known = read_env(self.people_file)
            email, password = known["APPROVER_EMAIL"], known["APPROVER_PASSWORD"]
        return person(service_urls(self.origin), email, password, self.ops)

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

    def levy(self, mailbox: str | None, bank_host: str) -> None:
        """The levy story's configuration in the team, from scripts/demo/team.json through the demo seed's own steps
        (one definition of the team's levy workflows): the egress it needs, the garnishment notice document type, and
        the levy workflows, published through the second person. The email intake is made only with a mailbox the team
        has connected; the bank module, the platform tools and the task types are the workspace's already."""
        spec = json.loads(demo_seed.TEAM_FILE.read_text())
        # Workflow and document type ids are the workspace's, one team each, and an id that has run is kept for good;
        # the team's copies carry its id's tail, so a second demo team does not collide with the first.
        tail = self.ops.removeprefix("team_")[:8]

        def own(name: str) -> str:
            return f"{name}_{tail}"

        kinds = [{**k, "id": own(k["id"])} for k in spec["documentTypes"]]
        levy = [
            {
                **w,
                "id": own(w["id"]),
                "workflows": {k: own(v) for k, v in (w.get("workflows") or {}).items()},
                "documentTypes": {k: own(v) for k, v in (w.get("documentTypes") or {}).items()},
            }
            for w in spec["workflows"]
            if demo_seed.levy_story(w)
        ]
        self.egress([*MAIL_HOSTS, bank_host], [])
        builder, approver = self.person("admin"), self.person("approver")
        demo_seed.ensure_document_types(builder, kinds)
        if mailbox:
            boxes = data(httpx.get(self.url("agents", "/v1/channels/mailboxes"), headers=self.as_admin(), timeout=30))
            if not any(b["address"] == mailbox and b.get("teamId") == self.ops for b in boxes):
                step(
                    False, "mailbox", f"{mailbox} is not connected in {self.ops}: connect it on Channels > Email first"
                )
                mailbox = None
        demo_seed.ensure_workflows(builder, approver, levy, {}, mailbox)
        FAILED.extend(demo_seed.FAILED)
        print(f"levy workflows in {self.ops}: {', '.join(w['id'] for w in levy)}")

    def bind_intake(self, wid: str, mailbox: str, document_workflow: str) -> str | None:
        """The team's Email received workflow `wid` reading `mailbox`, live. A workflow the team already has is
        repointed (its own copy, such as the demo team's); a seeded one the team lacks is saved from the seed with the
        rest of the mail workflows; any other id is saved as a copy of the seeded mail_intake that starts
        `document_workflow` per attachment. Returns the workflow the intake starts per attachment."""
        found = httpx.get(self.url("agents", f"/v1/workflows/definitions/{wid}"), headers=self.as_admin(), timeout=30)
        if found.status_code == 404:
            seeded = {
                w["id"]: w
                for w in json.loads((ROOT / "services/agents-service/seed/engine_workflows.json").read_text())
            }
            if wid in WORKFLOWS:
                self.workflows(mailbox)
                definition: dict[str, Any] = seeded[wid]
            else:
                definition = {k: v for k, v in seeded["mail_intake"].items() if k != "teamId"} | {"id": wid}
                for n in definition["nodes"]:
                    if n["type"] == "ops.trigger.email":
                        n["parameters"]["mailbox"] = mailbox
                    if n["type"] == "ops.action.workflow":
                        n["parameters"]["workflow"] = document_workflow
                self.publish(wid, definition)
        else:
            view = data(found)
            definition = {k: v for k, v in dict(view["definition"]).items() if k != "teamId"}
            triggers = [n for n in definition["nodes"] if n["type"] == "ops.trigger.email"]
            if not triggers:
                raise SystemExit(f"workflow {wid} in {self.ops} has no Email received trigger")
            if any(n["parameters"].get("mailbox") != mailbox for n in triggers) or view.get("stage") != "live":
                for n in triggers:
                    n["parameters"]["mailbox"] = mailbox
                self.publish(wid, definition)
            else:
                print(f"workflow {wid}: v{view.get('version')} live on {mailbox}")
        starts = [n for n in definition["nodes"] if n["type"] == "ops.action.workflow"]
        return str(starts[0]["parameters"]["workflow"]) if starts else None

    def mailbox_secret(self, name: str, value: str | None) -> bool:
        """Settings > Secrets, as a Security admin: `name` holds the mailbox password and the demo team may use it.
        An existing secret keeps its value; only its teams widen."""
        h = self.as_admin(SECURITY)
        listed = data(httpx.get(self.url("tools", "/v1/secrets"), headers=h, timeout=30))
        found = next((x for x in listed if x["name"] == name), None)
        if found is None:
            if not value:
                return step(False, "mailbox secret", f"{name} is not in Secrets; export DEMO_MAILBOX_PASSWORD")
            made = httpx.post(
                self.url("tools", "/v1/secrets"), json={"name": name, "value": value, "teams": [self.ops]}, headers=h
            )
            return step(made.status_code == 201, "mailbox secret", f"{name} made for {self.ops}: {made.status_code}")
        teams = found.get("teams")
        if teams is not None and self.ops not in teams:
            widened = httpx.patch(
                self.url("tools", f"/v1/secrets/{name}"), json={"teams": [*teams, self.ops]}, headers=h, timeout=30
            )
            return step(widened.status_code == 200, "mailbox secret", f"{name} now usable by {self.ops}")
        return step(True, "mailbox secret", f"{name} found, usable by {', '.join(teams or ['every team'])}")

    def connected_elsewhere(self, address: str) -> str | None:
        """The other team `address` is connected in, if any. A workspace connects an address once, and a mailbox can be
        neither removed nor moved to another team yet, so the demo runs in that team instead."""
        teams = data(httpx.get(self.url("platform", "/v1/teams"), headers=self.as_admin(), timeout=30))
        for team in teams:
            if team["id"] == self.ops:
                continue
            h = self.as_admin(team["id"])
            boxes = data(httpx.get(self.url("agents", "/v1/channels/mailboxes"), headers=h, timeout=30))
            if any(b["address"] == address and b.get("teamId") == team["id"] for b in boxes):
                return f"{team['name']} ({team['id']})"
        return None


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


def upload_notice(who: Session, name: str, suffix: str) -> str:
    """The notice through the console's upload (a ticket, the bytes, then complete) under a key of its own per walk:
    the demo seed's upload keys on the bytes alone, so the same notice under a second name is refused."""
    body = NOTICE.read_bytes()
    meta = {"name": name, "size": len(body), "mime": "application/pdf", "purpose": "case_attachment"}
    files = who("files")
    meta["digest"] = hashlib.sha256(body).hexdigest()
    ticket = data(files.post("/v1/files/uploads", json=meta, headers={"Idempotency-Key": f"mailbox-demo-{suffix}"}))
    if ticket.get("uploadUrl"):
        put = files.put(ticket["uploadUrl"], headers=ticket.get("headers") or {}, content=body)
        if put.status_code >= 400:
            raise SystemExit(f"upload of {name}: {put.status_code} {put.text[:300]}")
    done = data(files.post(f"/v1/files/uploads/{ticket['fileId']}/complete"))
    return str((done.get("file") or done)["id"])


def connect(demo: Demo, a: argparse.Namespace) -> str | None:
    """The mailbox connected in the team and the team's Email received workflow live on it; returns the workflow it
    starts per attachment, or None after a FAIL. A mailbox the team has already connected (an owner's Gmail, say) is
    used as it is; otherwise --imap and --smtp connect it the way a person does on Channels > Email."""
    admin = demo.as_admin()
    boxes = data(httpx.get(demo.url("agents", "/v1/channels/mailboxes"), headers=admin, timeout=30))
    box = next((b for b in boxes if b["address"] == a.mailbox and b.get("teamId") == demo.ops), None)
    if box is not None and not a.imap:
        tested = httpx.post(demo.url("agents", f"/v1/channels/mailboxes/{box['id']}/test"), headers=admin, timeout=90)
        result = tested.json().get("data") or {} if tested.status_code == 200 else {}
        steps = ", ".join(f"{x['title']}: {x['state']}" for x in result.get("steps") or [])
        if not step(bool(result.get("ok")), "mailbox connected", f"{box['id']} {a.mailbox} in {demo.ops}: {steps}"):
            return None
        return demo.bind_intake(a.intake_workflow, a.mailbox, a.document_workflow)
    if not (a.imap and a.smtp):
        step(False, "mailbox connected", f"{a.mailbox} is not connected in {demo.ops}; give --imap and --smtp")
        return None
    imap_host, imap_port = hostport(a.imap)
    smtp_host, smtp_port = hostport(a.smtp)
    # A workspace connects an address once: an address in another team is walked there, and nothing here changes.
    elsewhere = demo.connected_elsewhere(a.mailbox)
    if elsewhere:
        step(False, "mailbox connected", f"{a.mailbox} is connected in {elsewhere}; run the walk with that --team")
        return None
    # Settings > Secrets and Settings > Egress, as a Security admin.
    if not demo.mailbox_secret(a.secret, a.mailbox_password):
        return None
    demo.egress([imap_host, smtp_host], [])
    # Channels > Email > Connect mailbox in the demo team, then Test connection.
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
                    "passwordSecret": a.secret,
                    "sender": "smtp",
                    "fromAddress": a.mailbox,
                    "smtpHost": smtp_host,
                    "smtpPort": smtp_port,
                    "smtpStarttls": True,
                    "senderSecret": a.secret,
                },
                headers=admin,
                timeout=30,
            )
        )
    elif box.get("paused"):
        # Pausing and resuming is the channel's (PATCH /v1/channels/{id}), for every kind of channel.
        data(httpx.patch(demo.url("agents", f"/v1/channels/{box['id']}"), json={"paused": False}, headers=admin))
    tested = httpx.post(demo.url("agents", f"/v1/channels/mailboxes/{box['id']}/test"), headers=admin, timeout=90)
    result = tested.json().get("data") or {} if tested.status_code == 200 else {}
    steps = ", ".join(f"{x['title']}: {x['state']}" for x in result.get("steps") or [])
    step(bool(result.get("ok")), "mailbox connected", f"{box['id']} {a.mailbox} in {demo.ops}: {steps or tested.text}")
    # The team's Email received trigger picks the mailbox; a change is published and approved by a second person.
    return demo.bind_intake(a.intake_workflow, a.mailbox, a.document_workflow)


def walk(demo: Demo, a: argparse.Namespace) -> int:
    admin = demo.as_admin()
    if a.mailbox:
        document_workflow = connect(demo, a)
        if document_workflow is None:
            return len(FAILED)
    else:
        # No mailbox in the team yet: the notice is uploaded, and with no mailbox to answer from the acknowledgement is
        # declined.
        document_workflow = a.document_workflow

    suffix = uuid.uuid4().hex[:8]
    sender = f"clerk+{suffix}@court.example"
    subject, filename = f"Levy notice {suffix}", f"levy-{suffix}.pdf"
    lead = demo.person("admin")
    ids: dict[str, Any] = {}

    def run(run_id: str) -> dict[str, Any]:
        return dict(data(httpx.get(demo.url("agents", f"/v1/runs/{run_id}"), headers=admin, timeout=30)))

    def out_of(r: dict[str, Any], node: str) -> Any:
        return next((s.get("output") for s in r.get("steps", []) if s.get("nodeId") == node), None)

    if a.upload:
        # The notice uploaded to Files and its document run started, as the run API allows: every step after the
        # inbound email, with the reply still sent from the connected mailbox.
        file_id = upload_notice(lead, filename, suffix)
        input_ = {"fileId": file_id, "name": filename, "from": sender, "subject": subject, "mailbox": a.mailbox or ""}
        started = data(
            httpx.post(
                demo.url("agents", "/v1/runs"),
                json={"workflowId": document_workflow, "runKey": f"mailbox-demo:{suffix}", "input": input_},
                headers=admin,
                timeout=60,
            )
        )
        print(f"      uploaded {filename} as {file_id}; started {document_workflow}", flush=True)
        doc: dict[str, Any] | None = run(str(started["runId"]))
    else:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, a.mailbox, subject
        msg["Message-ID"] = make_msgid(idstring=suffix, domain="court.example")
        msg.set_content("Please find the garnishment notice attached.")
        msg.add_attachment(NOTICE.read_bytes(), maintype="application", subtype="pdf", filename=filename)
        send_host, send_port = hostport(a.send_smtp)
        with smtplib.SMTP(send_host, send_port, timeout=20) as smtp:
            if a.send_user:
                # A real provider (Ethereal) takes mail only over STARTTLS from a signed-in account.
                smtp.starttls(context=tls_context())
                smtp.login(a.send_user, a.mailbox_password)
            smtp.send_message(msg)
        print(f"      sent '{subject}' from {sender} to {a.mailbox}", flush=True)

        def intake_run() -> dict[str, Any] | None:
            rows = data(
                httpx.get(
                    demo.url("agents", "/v1/runs"),
                    params={"workflowId": a.intake_workflow},
                    headers=admin,
                    timeout=30,
                )
            )["data"]
            for row in rows[:20]:
                got = run(row["id"])
                if suffix in str(got.get("input")):
                    return got
            return None

        intake = until(f"the {a.intake_workflow} run", intake_run)
        if not step(intake is not None, "run started", f"{a.intake_workflow} {intake['id']}" if intake else "no run"):
            return len(FAILED)
        ids["intake"] = intake["id"]
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

        doc = until("the document run", document_run)
    if not step(doc is not None, "document run", f"{doc['workflowId']} {doc['id']}" if doc else "no document run"):
        return len(FAILED)
    ids["document"] = doc["id"]
    read = until("the read step", lambda: out_of(run(doc["id"]), "read"))
    records = (read or {}).get("records") or []
    step(bool(records), "fields read", f"{len(records)} debtor(s): {[r['values'].get('name') for r in records]}")

    def check_or_cases() -> dict[str, Any] | None:
        got = run(doc["id"])
        return got if (got.get("waiting") or {}).get("node") == "check" or out_of(got, "open") else None

    first = until("the check or the cases", check_or_cases) or {}
    if (first.get("waiting") or {}).get("node") == "check":
        try:
            decide(demo.person("approver"), doc["id"], {"decision": "approved", "reason": "Demo: the read is right"})
            step(True, "check Human Task", "approved")
        except Refused as e:
            step(False, "check Human Task", str(e))
    cases = until("the levy cases", lambda: out_of(run(doc["id"]), "open"))
    case_runs = [r["runId"] for r in (cases or {}).get("runs", [])]

    def settled() -> list[dict[str, Any]] | None:
        rows = [run(x) for x in case_runs]
        return rows if rows and all(r["status"] in ("waiting", "succeeded", "failed") for r in rows) else None

    levy = until("the levy cases to settle", settled) or []
    opened: list[str] = []
    unmatched: list[str] = []
    for r in levy:
        case_id = ((out_of(r, "case") or out_of(r, "case_unmatched")) or {}).get("caseId")
        got = httpx.get(demo.url("agents", f"/v1/cases/{case_id}"), headers=admin, timeout=30) if case_id else None
        if got is None or got.status_code != 200:
            continue
        c = got.json()["data"]
        opened.append(f"{case_id} {c['subject']} [{c.get('customerId') or 'no customer'}]")
        if r.get("outcome") == "not_matched" and not c.get("customerId"):
            unmatched.append(f"{case_id} {c['subject']}")
    ids["cases"] = [o.split(" ", 1)[0] for o in opened]
    step(len(opened) == len(levy) == len(records) > 0, "case per debtor", "; ".join(opened) or "none")
    step(bool(unmatched), "unmatched debtor's own case", "; ".join(unmatched) or "no debtor ended not_matched")

    # Each matched debtor waits on a "Levy notice" Human Task: a person holds what the notice asks for, up to what the
    # account has free, and the hold is placed at the bank.
    approver = demo.person("approver")

    def past_review(run_id: str) -> dict[str, Any] | None:
        """The run once the hold ran: ended, or back at the review with the bank's refusal."""
        got = run(run_id)
        return got if got["status"] in ("succeeded", "failed", "cancelled") or out_of(got, "hold") else None

    waiting = [r for r in levy if (r.get("waiting") or {}).get("node") == "review"]
    held: list[str] = []
    for r in waiting:
        record = r["input"]["record"]
        accounts = out_of(r, "accounts") or []
        account = accounts[0] if accounts else {}
        free = float(account.get("balance") or 0) - sum(float(h["amount"]) for h in account.get("holds") or [])
        amount = round(min(float(record.get("amount") or 0), free), 2)
        # An account with nothing free (earlier walks' holds stay at the bank stand-in) is flagged instead.
        body: dict[str, Any] = (
            {"decision": "hold", "reason": "Demo: hold the amount the notice names", "inputs": {"amount": amount}}
            if amount > 0
            else {"decision": "flag", "reason": "Demo: nothing free to hold on the account"}
        )
        try:
            decide(approver, r["id"], body)
        except Refused as e:
            step(False, f"hold for {record.get('name')}", str(e))
            continue
        ended = until(f"the hold for {record.get('name')}", lambda r=r: past_review(r["id"])) or {}
        if body["decision"] == "flag":
            flagged = ended.get("outcome") == "flagged"
            step(flagged, f"flag for {record.get('name')}", f"{r['id']} {ended.get('outcome')}: no free funds")
            if flagged:
                held.append(f"{record.get('name')}: flagged, nothing free on {account.get('id')}")
            continue
        hold = out_of(ended, "hold") or {}
        ok = ended.get("outcome") == "held" and bool(hold.get("id"))
        step(ok, f"hold for {record.get('name')}", f"{r['id']} {ended.get('outcome')}: {hold}")
        if ok:
            held.append(f"{record.get('name')}: {hold['id']} {hold.get('amount')} on {account.get('id')}")
            if a.bank_env:
                key = read_env(a.bank_env.expanduser())["FAKE_BANK_KEY"]
                at_bank = httpx.get(f"{a.bank}/accounts/{account['id']}", headers={"X-Api-Key": key}, timeout=60)
                there = (
                    [h for h in (at_bank.json().get("holds") or []) if h["id"] == hold["id"]]
                    if at_bank.is_success
                    else []
                )
                step(
                    bool(there),
                    f"bank told of {hold['id']}",
                    f"{a.bank}/accounts/{account['id']}: {there or at_bank.status_code}",
                )
    ids["levy"] = [r["id"] for r in levy]
    step(bool(waiting) and len(held) == len(waiting), "holds proposed and approved", "; ".join(held) or "none")

    def at_ack() -> dict[str, Any] | None:
        got = run(doc["id"])
        return got if (got.get("waiting") or {}).get("node") == "ack" else None

    paused = until("the acknowledge task", at_ack)
    if not step(paused is not None, "acknowledge Human Task", f"{doc['id']} waits at 'ack'" if paused else "none"):
        return len(FAILED)
    if not a.mailbox:
        try:
            decide(lead, doc["id"], {"decision": "rejected", "reason": "Demo: no mailbox to answer from"})
        except Refused as e:
            step(False, "acknowledgement declined", str(e))
            return len(FAILED)

        def ended_run() -> dict[str, Any] | None:
            got = run(doc["id"])
            return got if got.get("outcome") else None

        ended = until("the document run to end", ended_run)
        outcome = (ended or {}).get("outcome")
        step(outcome == "cases_opened", "acknowledgement declined", f"no mailbox in {demo.ops}: {outcome}")
        print(f"      ids: {json.dumps(ids)}", flush=True)
        return len(FAILED)
    try:
        decide(lead, doc["id"], {"decision": "approved", "reason": "Demo: acknowledge the notice"})
        step(True, "acknowledged", f"as {demo.admin_email}")
    except Refused as e:
        step(False, "acknowledged", str(e))

    def reply() -> str | None:
        if a.read_imap:
            return imap_reply(a, sender, suffix)
        if a.read_mailpit:
            r = httpx.get(f"{a.read_mailpit}/api/v1/search", params={"query": f'to:"{sender}"'}, timeout=30)
            found = [m for m in r.json().get("messages", []) if suffix in str(m.get("Subject"))]
            return f"'{found[0]['Subject']}' from {found[0]['From']['Address']} to {sender}" if found else None
        # No mailbox to look in: the reply step's answer from the mailbox's SMTP sender.
        out = out_of(run(doc["id"]), "reply") or {}
        return f"sent by {a.mailbox}'s SMTP to {sender}: {out}" if out.get("status") == "sent" else None

    sent = until("the reply", reply)
    step(sent is not None, "reply sent", sent or f"none to {sender}")
    print(f"      ids: {json.dumps(ids)}", flush=True)
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
    for name in ("seed", "egress", "levy", "walk"):
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
    levy = sub.choices["levy"]
    levy.add_argument("--team", required=True, help="the team the levy story is set up in")
    levy.add_argument("--bank", default="https://<your-app>-bank.fly.dev", help="the bank stand-in's origin")
    w = sub.choices["walk"]
    w.add_argument("--imap", help="host:port the services read the mailbox at, to connect it")
    w.add_argument("--smtp", help="host:port the services send replies through, to connect it")
    w.add_argument("--send-smtp", help="host:port this machine sends the notice through (not with --upload)")
    w.add_argument("--team", default=SECURITY, help="the team that connects the mailbox and runs the demo")
    w.add_argument(
        "--intake-workflow", default="mail_intake", help="the team's workflow with the Email received trigger"
    )
    w.add_argument(
        "--document-workflow",
        default="mail_document",
        help="the workflow a new intake starts per attachment, when --intake-workflow is not in the team yet",
    )
    w.add_argument("--secret", default="DEMO_MAILBOX_PASSWORD", help="the Secrets-page secret holding the password")
    w.add_argument("--upload", action="store_true", help="upload the notice and start its document run, no email")
    w.add_argument("--bank", default="https://<your-app>-bank.fly.dev", help="the bank stand-in's origin")
    w.add_argument("--bank-env", type=Path, help="FAKE_BANK_KEY, to find each hold at the bank stand-in")
    found = w.add_mutually_exclusive_group()
    found.add_argument("--read-mailpit", help="the reply sender's Mailpit API, where the reply is found")
    found.add_argument("--read-imap", help="host:port of the mailbox's IMAP over TLS, where the reply is found")
    w.add_argument("--send-user", help="sign in to --send-smtp as this account, over STARTTLS")
    w.add_argument(
        "--mailbox-password",
        default=os.environ.get("DEMO_MAILBOX_PASSWORD"),
        help="the mailbox's password; default the DEMO_MAILBOX_PASSWORD environment variable, so it is never typed. "
        "Needed to make the secret, to send the notice as --send-user and to read the reply over IMAP",
    )
    a = ap.parse_args()
    if a.cmd == "walk" and not a.upload and not (a.send_smtp and a.mailbox):
        ap.error("walk needs --mailbox and --send-smtp to email the notice, or --upload")
    demo = Demo(a.origin, a.admin_env.expanduser(), a.people.expanduser(), getattr(a, "team", SECURITY))
    if a.cmd == "egress":
        demo.egress(list(MAIL_HOSTS), [])
    elif a.cmd == "levy":
        demo.levy(a.mailbox, urlparse(a.bank).hostname or a.bank)
        sys.exit(len(FAILED))
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
