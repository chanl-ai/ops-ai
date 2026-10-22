"""Seeds the demo team on any Ops AI install through its public HTTP API only (c-383).

    uv run python scripts/demo/seed_demo_team.py --origin http://localhost:3016 --admin-env .run/demo.env
    uv run python scripts/demo/seed_demo_team.py --origin https://<staging host> --admin-env <file>

`--origin` is the install's public address. One that serves `/api/<service>/` (deploy/fly/Caddyfile) is used as it
is; a local console origin reaches each service on its own port (OPS_<SERVICE>_PORT, the shared stack's defaults).
`--admin-env` names a file of KEY=value lines (scripts/demo/demo.env.example): a workspace admin's email and password,
who creates the team and the Security-team settings it needs; OPS_DEMO_PASSWORD, which each demo person sets when
accepting their invitation and docs/usecases/lib/capture_demo.mjs signs in with; and, optionally, the model alias the
agents run on and the team mailbox's servers. Without the mailbox lines the levy email story is skipped.

Everything the team holds is read from team.json (people, the handbooks' text, prompts, runs, cases, chats) and
workflows/ beside this script, and from the seeded levy workflows and document type. Each record is looked up by name
or key before it is made, so a second run finds everything and makes nothing; every line printed says FOUND, MADE,
SKIP or FAIL, and the exit status is the number of FAIL lines.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import smtplib
import sys
import time
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

HERE = Path(__file__).resolve().parent
TEAM_FILE = HERE / "team.json"
SERVICES = ("platform", "agents", "tools", "kb", "files", "documents")
LOCAL_PORTS = {"platform": 8710, "agents": 8700, "tools": 8720, "kb": 8740, "files": 8750, "documents": 8760}
WAIT_S = 120.0

FAILED: list[str] = []


def say(state: str, what: str, detail: str = "") -> None:
    if state == "FAIL":
        FAILED.append(what)
    print(f"{state:<6} {what}{f': {detail}' if detail else ''}", flush=True)


class Refused(Exception):
    def __init__(self, r: httpx.Response) -> None:
        super().__init__(f"{r.request.method} {r.request.url.path} answered {r.status_code}: {r.text[:400]}")
        self.status = r.status_code
        try:
            self.code = str((r.json().get("error") or {}).get("code") or "")
        except ValueError:
            self.code = ""


def data(r: httpx.Response) -> Any:
    if r.status_code >= 400:
        raise Refused(r)
    if not r.content:
        return None
    body = r.json()
    return body.get("data") if isinstance(body, dict) and "data" in body else body


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def service_urls(origin: str) -> dict[str, str]:
    """`/api/<service>` on an origin that routes them, else each service on its local port."""
    origin = origin.rstrip("/")
    try:
        routed = httpx.get(f"{origin}/api/platform/v1/health", timeout=10).status_code == 200
    except httpx.HTTPError:
        routed = False
    if routed:
        return {s: f"{origin}/api/{s}" for s in SERVICES}
    host = httpx.URL(origin).host
    if host not in {"localhost", "127.0.0.1"}:
        raise SystemExit(f"seed: {origin} serves no /api/platform/v1/health and is not a local console")
    return {s: f"http://127.0.0.1:{os.environ.get(f'OPS_{s.upper()}_PORT', LOCAL_PORTS[s])}" for s in SERVICES}


@dataclass
class Session:
    """One signed-in person: a client per service, acting in `team` (X-Team-Id) once it is set."""

    urls: dict[str, str]
    token: str
    email: str
    team: str | None = None
    # Kept for a step-up, which asks the person for their password again.
    password: str = field(default="", repr=False)
    name: str = ""
    clients: dict[str, httpx.Client] = field(default_factory=dict)

    def __call__(self, service: str) -> httpx.Client:
        if service not in self.clients:
            self.clients[service] = httpx.Client(base_url=self.urls[service], timeout=90)
        client = self.clients[service]
        client.headers["Authorization"] = f"Bearer {self.token}"
        if self.team:
            client.headers["X-Team-Id"] = self.team
        else:
            client.headers.pop("X-Team-Id", None)
        return client


def sign_in(urls: dict[str, str], email: str, password: str, team: str | None = None) -> Session:
    r = httpx.post(f"{urls['platform']}/v1/auth/sign-in", json={"email": email, "password": password}, timeout=30)
    return Session(urls, str(data(r)["token"]), email, team, password)


def until(probe: Any, seconds: float = WAIT_S, every: float = 1.5) -> Any:
    """`probe()` until it returns something truthy, or None after `seconds`."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        found = probe()
        if found:
            return found
        time.sleep(every)
    return None


def items(page: Any) -> list[dict[str, Any]]:
    """The rows of a list answer, whichever envelope the route uses."""
    if isinstance(page, list):
        return page
    if isinstance(page, dict):
        for key in ("data", "items", "rows", "results"):
            if isinstance(page.get(key), list):
                return page[key]
    return []


# ── Team and people ──────────────────────────────────────────────────────────────────────────────────────────────


def ensure_team(admin: Session, spec: dict[str, Any]) -> str:
    found = items(data(admin("platform").get("/v1/settings/teams", params={"search": spec["name"]})))
    team = next((t for t in found if t["name"].lower() == spec["name"].lower()), None)
    if team:
        if team["status"] != "active":
            data(admin("platform").post(f"/v1/settings/teams/{team['id']}/restore"))
            say("MADE", f"team {spec['name']}", "restored from archived")
        else:
            say("FOUND", f"team {spec['name']}", team["id"])
        return str(team["id"])
    made = data(admin("platform").post("/v1/settings/teams", json={"name": spec["name"], "admin": admin.email}))
    say("MADE", f"team {spec['name']}", made["id"])
    return str(made["id"])


def ensure_people(admin: Session, team: str, people: list[dict[str, Any]], password: str) -> dict[str, Session]:
    """Each person by invitation, as a bank adds one: the admin invites, the person accepts with a name and password."""
    on_team = Session(admin.urls, admin.token, admin.email, team)
    members = {m["email"].lower(): m for m in items(data(on_team("platform").get("/v1/settings/members")))}
    sessions: dict[str, Session] = {}
    for person in people:
        email = person["email"].lower()
        member = members.get(email)
        if member and member["status"] == "active":
            say("FOUND", f"person {person['name']}", f"{member['role']} in the team")
        else:
            if member:  # an earlier run's invitation that was never accepted
                data(on_team("platform").post("/v1/settings/members/delete", json={"ids": [member["id"]]}))
            invited = data(
                on_team("platform").post(
                    "/v1/settings/members/invite", json={"emails": [email], "role": person["role"]}
                )
            )
            token = (invited.get("invites") or [{}])[0].get("token")
            if not token:
                say("FAIL", f"person {person['name']}", f"no invitation made: {json.dumps(invited)[:300]}")
                continue
            accept_invite(admin.urls, token, email, person["name"], password)
            say("MADE", f"person {person['name']}", f"{person['role']}, {email}")
        sessions[person["key"]] = sign_in(admin.urls, email, password, team)
        sessions[person["key"]].name = person["name"]
    return sessions


def accept_invite(urls: dict[str, str], token: str, email: str, name: str, password: str) -> None:
    """Accepts an invitation: a new person with a name and password; a person who already has an account (a member of
    another team) signs in first and accepts with their own session, as platform-service requires."""
    r = httpx.post(
        f"{urls['platform']}/v1/invites/{token}/accept", json={"name": name, "password": password}, timeout=30
    )
    try:
        data(r)
    except Refused as refused:
        if refused.code != "sign_in_as_invitee":
            raise
        own = sign_in(urls, email, password)
        r = httpx.post(
            f"{urls['platform']}/v1/invites/{token}/accept",
            json={"name": name},
            headers={"Authorization": f"Bearer {own.token}"},
            timeout=30,
        )
        data(r)


def ensure_members(admin: Session, team: str, members: list[tuple[str, str]], password: str) -> None:
    """`--member email:role`: people outside team.json (the logins a person demonstrates with) join the team with their
    role, each accepting the invitation as themselves; one already active in it is left as it is."""
    on_team = Session(admin.urls, admin.token, admin.email, team)
    known = {m["email"].lower(): m for m in items(data(on_team("platform").get("/v1/settings/members")))}
    for email, role in members:
        member = known.get(email.lower())
        if member and member["status"] == "active":
            if member["role"] != role:
                data(on_team("platform").post("/v1/settings/members/role", json={"ids": [member["id"]], "role": role}))
                say("MADE", f"member {email}", f"role {member['role']} -> {role}")
            else:
                say("FOUND", f"member {email}", role)
            continue
        if member:  # an invitation never accepted, perhaps with another role
            data(on_team("platform").post("/v1/settings/members/delete", json={"ids": [member["id"]]}))
        invited = data(on_team("platform").post("/v1/settings/members/invite", json={"emails": [email], "role": role}))
        token = (invited.get("invites") or [{}])[0].get("token")
        if not token:
            say("FAIL", f"member {email}", f"no invitation made: {json.dumps(invited)[:300]}")
            continue
        accept_invite(admin.urls, token, email, email.split("@", 1)[0], password)
        say("MADE", f"member {email}", role)


ADMIN: list[Session] = []
ADMIN: list[Session] = []


def approving_team(r: httpx.Response) -> str | None:
    """The team a 403 says approves this step, when the caller is not in it."""
    if r.status_code != 403:
        return None
    error = (r.json().get("error") or {}) if r.content else {}
    return (
        str((error.get("details") or {}).get("teamId") or "") or None if error.get("code") == "role_required" else None
    )


def join_team(admin: Session, person: Session, team_id: str, role: str) -> None:
    """`person` joins `team_id` with `role` by invitation, accepted with their own session; their token is renewed so
    it carries the team."""
    there = sign_in(admin.urls, admin.email, admin.password, team_id)
    members = {m["email"].lower(): m for m in items(data(there("platform").get("/v1/settings/members")))}
    if (members.get(person.email) or {}).get("status") != "active":
        invited = data(
            there("platform").post("/v1/settings/members/invite", json={"emails": [person.email], "role": role})
        )
        token = (invited.get("invites") or [{}])[0].get("token")
        accepted = httpx.post(
            f"{admin.urls['platform']}/v1/invites/{token}/accept",
            json={"name": person.name or person.email},
            headers={"Authorization": f"Bearer {person.token}"},
            timeout=30,
        )
        data(accepted)
        say("MADE", f"person {person.email} in {team_id}", f"{role}, to approve that team's tool writes")
    person.token = sign_in(person.urls, person.email, person.password, person.team).token


# ── Files and knowledge ──────────────────────────────────────────────────────────────────────────────────────────


def upload(who: Session, name: str, body: bytes, mime: str, purpose: str) -> str:
    """The console's upload: a ticket, the bytes, then complete. Files-service dedupes on the digest, so the same
    bytes uploaded again answer the file already stored."""
    meta = {
        "name": name,
        "size": len(body),
        "mime": mime,
        "purpose": purpose,
        "digest": hashlib.sha256(body).hexdigest(),
    }
    files = who("files")
    ticket = data(
        files.post("/v1/files/uploads", json=meta, headers={"Idempotency-Key": f"demo-{meta['digest'][:32]}"})
    )
    if ticket.get("uploadUrl"):
        # The local storage backend's ticket is files-service's own content route, which wants the caller's token; a
        # signed storage URL ignores it.
        put = files.put(ticket["uploadUrl"], headers=ticket.get("headers") or {}, content=body)
        if put.status_code == 409:  # the same Idempotency-Key: an earlier run stored these bytes
            return str(ticket["fileId"])
        if put.status_code >= 400:
            raise Refused(put)
    done = data(files.post(f"/v1/files/uploads/{ticket['fileId']}/complete"))
    return str((done.get("file") or done)["id"])


def ensure_knowledge(who: Session, bases: list[dict[str, Any]]) -> dict[str, str]:
    kb = who("kb")
    ids: dict[str, str] = {}
    for base in bases:
        listed = items(data(kb.get("/v1/knowledge-bases", params={"search": base["name"], "pageSize": 100})))
        found = next((b for b in listed if b["name"].lower() == base["name"].lower()), None)
        if found and any(s.get("itemsContributed") for s in found.get("sources") or []):
            say("FOUND", f"knowledge base {base['name']}", found["id"])
            ids[base["key"]] = str(found["id"])
            continue
        made = found or data(
            kb.post(
                "/v1/knowledge-bases",
                json={
                    "name": base["name"],
                    "description": base["description"],
                    "color": base.get("color", "blue"),
                    "owner": who.email,
                },
            )
        )
        # A base an earlier run made but did not fill keeps the source it made, rather than gaining a second one.
        sources = [x.get("sourceId") for x in (found or {}).get("sources") or []]
        source = (
            {"id": sources[0]}
            if sources
            else data(
                kb.post(
                    "/v1/sources",
                    json={"type": "file", "name": base["source"], "kbIds": [made["id"]], "sensitivity": "internal"},
                )
            )
        )
        file_ids = [
            upload(who, doc["name"], doc["text"].encode(), "text/markdown", "knowledge_source")
            for doc in base["documents"]
        ]
        data(kb.post(f"/v1/sources/{source['id']}/files", json={"fileIds": file_ids}))
        run = data(kb.post(f"/v1/sources/{source['id']}/sync"))
        say(
            "MADE",
            f"knowledge base {base['name']}",
            f"{made['id']}, {len(file_ids)} documents, sync {json.dumps(run.get('counts'))}",
        )
        ids[base["key"]] = str(made["id"])
    return ids


# ── Agents ───────────────────────────────────────────────────────────────────────────────────────────────────────


def decide_publish(approver: Session, review: dict[str, Any], what: str) -> None:
    """A publish waits in Human Tasks for a person other than the builder; the approver approves it there."""
    if review.get("status") in {"approved", "published"} or review.get("decidedAt"):
        say("MADE", f"{what} publish", "live at once: the team's publish policy asks for no review")
        return
    decided = data(
        approver("agents").post(
            f"/v1/publish-requests/{review['id']}/decision",
            json={
                "decision": "approved",
                "reason": "Checked the instructions, tools and knowledge against the team's procedures.",
            },
        )
    )
    say("MADE", f"{what} publish", f"approved by {approver.email} ({decided.get('status')})")


@dataclass
class Models:
    """Which alias the demo agents answer on. The seed's own turns run on `scripted` (the fake model's committed rules);
    with `live` set, the agents are left on it at the end so a person's next chat gets a real model. An agent is moved
    back to `scripted` only when a run or chat is about to be made."""

    scripted: str = "default"
    live: str | None = None
    builder: Session | None = None
    approver: Session | None = None
    agents: dict[str, str] = field(default_factory=dict)

    @property
    def accepted(self) -> set[str]:
        return {self.scripted, *([self.live] if self.live else [])}

    def move(self, alias: str, why: str) -> None:
        assert self.builder and self.approver
        api = self.builder("agents")
        for agent_id in self.agents.values():
            detail = data(api.get(f"/v1/agents/{agent_id}"))
            if detail.get("model") == alias:
                continue
            patched = data(api.patch(f"/v1/agents/{agent_id}", json={"model": alias, "note": why}))
            review = data(
                api.post(f"/v1/agents/{agent_id}/publish-requests", json={"version": patched["version"], "note": why})
            )
            decide_publish(self.approver, review, f"agent {detail['name']} on {alias} v{patched['version']}")

    def scripted_now(self) -> None:
        self.move(self.scripted, "Scripted answers while the demo's chats and runs are made.")

    def live_now(self) -> None:
        if self.live:
            self.move(self.live, "Back on the live model for people's own chats.")


MODELS = Models()


def ensure_agents(
    builder: Session, approver: Session, agents: list[dict[str, Any]], knowledge: dict[str, str], model: str
) -> dict[str, str]:
    """Each agent with its instructions, tools and knowledge, published. A published agent that differs from the
    file gets a new version, published the same way."""
    api = builder("agents")
    ids: dict[str, str] = {}
    for agent in agents:
        wanted = {
            "role": agent["role"],
            "instructions": agent["instructions"],
            "model": model,
            "toolIds": agent["tools"],
            "collections": [knowledge[k] for k in agent["knowledge"]],
            # Memory writes a line per turn through its own model alias; the demo's turns are scripted.
            "memory": {"enabled": False},
        }
        listed = items(data(api.get("/v1/agents", params={"search": agent["name"], "pageSize": 50})))
        found = next((a for a in listed if a["name"] == agent["name"] and a.get("teamId") == builder.team), None)
        if found:
            detail = data(api.get(f"/v1/agents/{found['id']}"))
            have = {k: detail.get(k) for k in wanted} | {
                "memory": {"enabled": bool((detail.get("memory") or {}).get("enabled"))}
            }
            # An agent the last run moved to the live alias (OPS_DEMO_LIVE_MODEL_ALIAS) is as the file wants it.
            if have["model"] in MODELS.accepted:
                have["model"] = model
            if detail.get("publishedVersion") and have == wanted:
                say("FOUND", f"agent {agent['name']}", f"{found['id']} v{detail['publishedVersion']}")
                ids[agent["key"]] = str(found["id"])
                continue
        else:
            found = data(
                api.post(
                    "/v1/agents",
                    json={
                        "name": agent["name"],
                        "role": agent["role"],
                        "model": model,
                        "channels": ["chat"],
                        "instructions": agent["instructions"],
                    },
                )
            )
            say("MADE", f"agent {agent['name']}", str(found["id"]))
        patched = data(
            api.patch(
                f"/v1/agents/{found['id']}",
                json={**wanted, "note": agent.get("note", "Instructions, tools and knowledge for the team.")},
            )
        )
        review = data(
            api.post(
                f"/v1/agents/{found['id']}/publish-requests",
                json={"version": patched["version"], "note": "Release for the team."},
            )
        )
        decide_publish(approver, review, f"agent {agent['name']} v{patched['version']}")
        ids[agent["key"]] = str(found["id"])
    return ids


# ── Document types ───────────────────────────────────────────────────────────────────────────────────────────────

SEEDED_DOCUMENT_TYPES = HERE.parents[1] / "services" / "documents-service" / "scripts" / "seed_document_types.py"


def ensure_document_types(builder: Session, kinds: list[dict[str, Any]]) -> None:
    """The team's own copy of a seeded document type (its fields from documents-service's seed), under its own id."""
    loaded = importlib.util.spec_from_file_location("seed_document_types", SEEDED_DOCUMENT_TYPES)
    assert loaded and loaded.loader
    module = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(module)
    for kind in kinds:
        body = {
            **getattr(module, kind["seed"]),
            "id": kind["id"],
            "name": kind["name"],
            "description": kind["description"],
        }
        made = builder("documents").post("/v1/document-types", json=body)
        if made.status_code == 409:
            # The id is taken in the workspace; it is this team's only if the team can read it.
            if builder("documents").get(f"/v1/document-types/{kind['id']}").status_code == 200:
                say("FOUND", f"document type {kind['name']}", kind["id"])
            else:
                say(
                    "FAIL",
                    f"document type {kind['name']}",
                    f"{kind['id']} is another team's: seed with --workflow-prefix",
                )
            continue
        data(made)
        say("MADE", f"document type {kind['name']}", f"{kind['id']} v1, {len(body['fields'])} fields")


# ── The team mailbox ─────────────────────────────────────────────────────────────────────────────────────────────


def hostport(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    return host, int(port)


def ensure_mailbox(admin: Session, lead: Session, env: dict[str, str], spec: dict[str, Any]) -> str | None:
    """The team's legal orders mailbox on Channels > Email, as an admin connects one: its password a Secrets-page
    secret only the team may use (set by a Security admin), then Test connection."""
    address = env.get("OPS_DEMO_MAILBOX")
    if not address:
        say("SKIP", "mailbox", "no OPS_DEMO_MAILBOX in the env file")
        return None
    imap_host, imap_port = hostport(env["OPS_DEMO_IMAP"])
    smtp_host, smtp_port = hostport(env["OPS_DEMO_REPLY_SMTP"])
    tls = env.get("OPS_DEMO_MAIL_TLS", "1") != "0"
    security_team = str(data(admin("platform").get("/v1/settings/workspace-teams"))["securityTeam"])
    security = sign_in(admin.urls, admin.email, admin.password, security_team)
    secret = spec["secret"]
    found = next((x for x in items(data(security("tools").get("/v1/secrets"))) if x["name"] == secret), None)
    if found is None:
        value = env.get("OPS_DEMO_MAILBOX_PASSWORD") or uuid.uuid4().hex
        data(security("tools").post("/v1/secrets", json={"name": secret, "value": value, "teams": [lead.team]}))
        say("MADE", f"secret {secret}", f"for team {lead.team} only")
    elif found.get("teams") is not None and lead.team not in (found.get("teams") or []):
        data(security("tools").patch(f"/v1/secrets/{secret}", json={"teams": [*(found.get("teams") or []), lead.team]}))
        say("MADE", f"secret {secret}", f"now usable by team {lead.team}")
    else:
        say("FOUND", f"secret {secret}")
    boxes = items(data(lead("agents").get("/v1/channels/mailboxes")))
    box = next((b for b in boxes if b["address"] == address), None)
    if box:
        say("FOUND", f"mailbox {address}", str(box["id"]))
    else:
        box = data(
            lead("agents").post(
                "/v1/channels/mailboxes",
                json={
                    "name": spec["name"],
                    "address": address,
                    "provider": "imap",
                    "imapHost": imap_host,
                    "imapPort": imap_port,
                    "imapTls": tls,
                    "passwordSecret": secret,
                    "sender": "smtp",
                    "fromAddress": address,
                    "smtpHost": smtp_host,
                    "smtpPort": smtp_port,
                    "smtpStarttls": tls,
                    "senderSecret": secret,
                },
            )
        )
        say("MADE", f"mailbox {address}", str(box["id"]))
    tested = data(lead("agents").post(f"/v1/channels/mailboxes/{box['id']}/test"))
    steps = ", ".join(f"{x['title']}: {x['state']}" for x in tested.get("steps") or [])
    say("FOUND" if tested.get("ok") else "FAIL", f"mailbox {address} test", steps)
    return address


# ── Workflows ────────────────────────────────────────────────────────────────────────────────────────────────────


def placeholders(value: Any, names: dict[str, str]) -> Any:
    """`{agent:<key>}` and `{workflow:<key>}` in a definition file name a record this run made, by its key."""
    if isinstance(value, str):
        return re.sub(r"\{(agent|workflow):(\w+)\}", lambda m: names[f"{m.group(1)}:{m.group(2)}"], value)
    if isinstance(value, list):
        return [placeholders(v, names) for v in value]
    if isinstance(value, dict):
        return {k: placeholders(v, names) for k, v in value.items()}
    return value


def same_definition(stored: dict[str, Any], wanted: dict[str, Any]) -> bool:
    """Whether the stored version is the file's, read as numbers (the service stores positions as floats)."""
    keys = ("name", "description", "nodes", "connections")

    def plain(d: dict[str, Any]) -> str:
        return json.dumps(json.loads(json.dumps({k: d.get(k) for k in keys}), parse_int=float), sort_keys=True)

    return plain(stored) == plain(wanted)


SEEDED_WORKFLOWS = HERE.parents[1] / "services" / "agents-service" / "seed" / "engine_workflows.json"


def definition_of(wf: dict[str, Any], names: dict[str, str], mailbox: str | None) -> dict[str, Any]:
    """The team's copy of a workflow: its own file under workflows/, or a seeded workflow (`seed`) under the team's id
    and name, with the workflows it starts renamed to the team's copies and its email trigger on the team's mailbox."""
    if "file" in wf:
        own = placeholders(json.loads((HERE / "workflows" / wf["file"]).read_text()), names)
        return own | {"id": wf.get("id") or own["id"]}
    seeded = {w["id"]: w for w in json.loads(SEEDED_WORKFLOWS.read_text())}[wf["seed"]]
    copy = {k: v for k, v in seeded.items() if k != "teamId"} | {
        "id": wf["id"],
        "name": wf["name"],
        "description": wf["description"],
    }
    for node in copy["nodes"]:
        params = node["parameters"]
        if node["type"] == "ops.action.workflow" and params.get("workflow") in wf.get("workflows", {}):
            params["workflow"] = wf["workflows"][params["workflow"]]
        kind = params.get("documentType")
        if isinstance(kind, dict) and kind.get("id") in wf.get("documentTypes", {}):
            params["documentType"] = {**kind, "id": wf["documentTypes"][kind["id"]], "version": 1}
        if node["type"] == "ops.trigger.email":
            # With no mailbox the trigger reads no mail; Start run still sends it a test email (c-466).
            if mailbox:
                params["mailbox"] = mailbox
            else:
                params.pop("mailbox", None)
    return copy


def levy_story(wf: dict[str, Any]) -> bool:
    """Whether a team.json workflow belongs to the levy story: a copy of a seeded levy workflow, which
    deploy/fly/staging/mailbox_demo.py levy makes under the team's own ids."""
    return "seed" in wf


def team_workflows(spec: dict[str, Any], *, no_levy: bool) -> list[dict[str, Any]]:
    """The workflows the seed makes: with `--no-levy` the levy walk makes the levy story's, so the seed leaves them out
    and the team has one copy of each."""
    return [wf for wf in spec["workflows"] if not (no_levy and levy_story(wf))]


def ensure_workflows(
    builder: Session, approver: Session, workflows: list[dict[str, Any]], names: dict[str, str], mailbox: str | None
) -> None:
    api = builder("agents")
    for wf in workflows:
        if wf.get("needsMailbox") and not mailbox:
            say("NOTE", f"workflow {wf['name']}", "no OPS_DEMO_MAILBOX: reads no mail; Start run sends test emails")
        definition = definition_of(wf, names, mailbox)
        wid = definition["id"]
        found = api.get(f"/v1/workflows/definitions/{wid}")
        view = data(found) if found.status_code == 200 else None
        same = view is not None and same_definition(view.get("definition") or {}, definition)
        if same and view.get("stage") == "live":
            say("FOUND", f"workflow {definition['name']}", f"{wid} v{view['version']} live")
            continue
        if not same:
            view = data(api.post("/v1/workflows/definitions", json={"definition": definition}))
            say("MADE", f"workflow {definition['name']}", f"{wid} v{view.get('version')}")
        review = data(
            api.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={"note": "First release for the team."})
        )
        decide_publish(approver, review, f"workflow {definition['name']}")


def ensure_tool_access(
    admin: Session, team: str, *, owning_team: str, modules: list[str], approver: Session, why: str
) -> None:
    """`--tool-access`: each of the team's live workflows is granted the operations of each module another team owns
    (the bank system, the platform tools), as a builder asks on the module's Access tab and that team's approver
    decides in Human Tasks. The grant is what lets the team's people see those modules and its runs call them (c-423,
    c-433). A workflow no team owns is left out; one already granted, or waiting, is not asked again."""
    ours = Session(admin.urls, admin.token, admin.email, team)
    flows = [
        w
        for w in items(data(ours("agents").get("/v1/workflows/definitions", params={"pageSize": 100})))
        if w.get("status") == "live"
    ]
    owner = sign_in(admin.urls, admin.email, admin.password, owning_team)
    approver.team = owning_team
    for module_id in modules:
        module = data(owner("tools").get(f"/v1/tool-modules/{module_id}"))
        operations = [o["name"] for o in module["operations"] if o.get("enabled", True)]
        for flow in flows:
            what = f"tool access {module['displayName']} for {flow['name']} ({flow['workflowId']})"
            held = [a for a in module.get("approvals") or [] if a["workflowId"] == flow["workflowId"]]
            if any(a["status"] == "approved" for a in held):
                say("FOUND", what, "approved")
                continue
            asked = next((a for a in held if a["status"] == "requested"), None)
            if asked is None:
                body = {
                    "workflowId": flow["workflowId"],
                    "environment": "production",
                    "operations": operations,
                    "expiresInDays": 365,
                    "justification": why,
                }
                # Asked by the module's own team, which reads the module; tools-service finds the workflow in any team.
                r = owner("tools").post(f"/v1/tool-modules/{module_id}/approvals", json=body)
                if r.status_code == 422:
                    say("SKIP", what, "no team owns the workflow")
                    continue
                asked = data(r)
            key = str(asked["reviewId"])
            review = until(lambda k=key: _review_by_key(approver, k), seconds=90)
            if review is None:
                say("FAIL", what, f"no Human Task for {key} within 90 s (is the workflow worker up?)")
                continue
            decide(approver, str(review["id"]), {"decision": "approve", "reason": why})
            say("MADE", what, f"approved by {approver.email}")


def _review_by_key(who: Session, key: str) -> dict[str, Any] | None:
    """The Human Task of a service event's run, once the run has reached it."""
    r = who("agents").get(f"/reviews/by-run-key/{key}")
    return data(r) if r.status_code == 200 else None


EXTRAS_FILE = HERE / "team_extras.json"


def ensure_extras(people: dict[str, Session], agents: dict[str, str], extras: dict[str, Any]) -> None:
    """`--extras`: what a bank team holds beside team.json's story: its shared skills and guardrails, each published
    through review, and the agent its chats start on. Each is found by name before it is made."""
    builder, approver, admin = people["builder"], people["approver"], people["admin"]
    have = {s["name"]: s for s in items(data(builder("agents").get("/v1/skills", params={"pageSize": 100})))}
    for skill in extras.get("skills", []):
        found = have.get(skill["name"]) or data(builder("agents").post("/v1/skills", json=skill))
        sid = str(found["id"])
        detail = data(builder("agents").get(f"/v1/skills/{sid}"))
        if detail.get("publishedVersion") is not None:
            say("FOUND", f"skill {skill['name']}", f"{sid} published")
            continue
        if not detail.get("pendingReviewId"):
            note = {"note": "For the team."}
            detail = data(builder("agents").post(f"/v1/skills/{sid}/publish-requests", json=note))
        # A skill's publish answers the skill; its open request is `pendingReviewId`, none when it went live at once.
        pending = detail.get("pendingReviewId")
        decide_publish(approver, {"id": pending} if pending else {"status": "published"}, f"skill {skill['name']}")
    rules = {g["name"]: g for g in items(data(builder("agents").get("/v1/guardrails", params={"pageSize": 100})))}
    for rule in extras.get("guardrails", []):
        found = rules.get(rule["name"]) or data(builder("agents").post("/v1/guardrails", json=rule))
        gid = str(found["id"])
        if found.get("publishedVersion") is not None:
            say("FOUND", f"guardrail {rule['name']}", f"{gid} published")
            continue
        if not found.get("pendingRequestId"):
            body = {"version": found.get("version") or 1, "note": "For the team."}
            found = data(builder("agents").post(f"/v1/guardrails/{gid}/publish-requests", json=body))
        pending = found.get("pendingRequestId")
        decide_publish(approver, {"id": pending} if pending else {"status": "published"}, f"guardrail {rule['name']}")
    if (key := extras.get("defaultAgent")) and key in agents:
        found = data(admin("agents").get("/chat/default-agent"))
        if found.get("agentId") == agents[key]:
            say("FOUND", "default chat agent", agents[key])
        else:
            data(admin("agents").put("/chat/default-agent", json={"agentId": agents[key]}))
            say("MADE", "default chat agent", agents[key])


# ── The levy notice by email ─────────────────────────────────────────────────────────────────────────────────────


def runs_of(who: Session, workflow: str) -> list[dict[str, Any]]:
    return items(data(who("agents").get("/v1/runs", params={"workflowId": workflow, "pageSize": 50})))


def step_out(run: dict[str, Any], node: str) -> Any:
    return next((st.get("output") for st in run.get("steps", []) if st.get("nodeId") == node), None)


def waiting_on(who: Session, run_id: str, node: str) -> dict[str, Any] | None:
    run = run_detail(who, run_id)
    return run if (run.get("waiting") or {}).get("node") == node else None


def ensure_levy_mail(
    people: dict[str, Session], env: dict[str, str], mailbox: str | None, spec: dict[str, Any]
) -> None:
    """A court registry emails a garnishment notice to the legal orders mailbox; the email trigger stores it in Files
    and starts the read, a case opens per debtor, and people decide the Human Tasks the story names."""
    lead = people["lead"]
    by_email = bool(mailbox and env.get("OPS_DEMO_SMTP"))
    doc_id = notice_by_email(lead, env, mailbox, spec) if by_email else notice_by_upload(lead, spec)
    if not doc_id:
        return
    read_and_decide(people, doc_id, spec, by_email=by_email)


def notice_by_upload(lead: Session, spec: dict[str, Any]) -> str | None:
    """With no mailbox to send to, a person uploads the notice and starts its read, as the run API allows; the rest of
    the story is the same."""
    notice = HERE.parents[1] / spec["attachment"]
    file_id = upload(lead, spec["filename"], notice.read_bytes(), "application/pdf", "case_attachment")
    started = data(
        lead("agents").post(
            "/v1/runs",
            json={
                "workflowId": spec["document"],
                "runKey": "demo-team:levy-notice-upload",
                "input": {
                    "fileId": file_id,
                    "name": spec["filename"],
                    "from": spec["from"],
                    "subject": spec["subject"],
                    "mailbox": "",
                },
            },
        )
    )
    say("MADE" if started.get("created") else "FOUND", "levy notice uploaded", f"run {started['runId']}")
    return str(started["runId"])


def notice_by_email(lead: Session, env: dict[str, str], mailbox: str | None, spec: dict[str, Any]) -> str | None:
    """A court registry emails the notice to the legal orders mailbox; the email trigger stores it in Files and starts
    the read. Returns the document run."""

    def sent() -> list[dict[str, Any]]:
        return [r for r in runs_of(lead, spec["intake"]) if spec["subject"] in json.dumps(r.get("input"))]

    def read_one(run: dict[str, Any]) -> bool:
        """Whether the notice this email run started was read: a notice that was not (a stopped stack, a missing
        document type) is sent again, since nothing came of it."""
        docs = (step_out(run_detail(lead, run["id"]), "each") or {}).get("runs") or []
        return (bool(docs) and step_out(run_detail(lead, docs[0]["runId"]), "open") is not None) or any(
            run_detail(lead, d["runId"]).get("status") not in SETTLED for d in docs
        )

    before = sent()
    intake = next((r for r in before if read_one(r)), None)
    if intake:
        say("FOUND", "levy notice email", f"run {intake['id']}")
    else:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = spec["from"], mailbox, spec["subject"]
        msg["Message-ID"] = make_msgid(idstring="levy-notice", domain=spec["from"].split("@")[1])
        msg.set_content(spec["body"])
        notice = HERE.parents[1] / spec["attachment"]
        msg.add_attachment(notice.read_bytes(), maintype="application", subtype="pdf", filename=spec["filename"])
        host, port = hostport(env["OPS_DEMO_SMTP"])
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.send_message(msg)
        say("MADE", "levy notice email", f"from {spec['from']} to {mailbox}")
        known = {r["id"] for r in before}
        intake = until(lambda: next((r for r in sent() if r["id"] not in known), None), seconds=180)
        if intake is None:
            say(
                "FAIL", "levy notice email", "no run of the email workflow after three minutes (is the worker polling?)"
            )
            return None
        say("MADE", "levy notice run", str(intake["id"]))
    doc_id = until(
        lambda: ((step_out(run_detail(lead, intake["id"]), "each") or {}).get("runs") or [{}])[0].get("runId")
    )
    if not doc_id:
        say("FAIL", "levy notice read", "the email run started no document run")
        return None
    return str(doc_id)


def read_and_decide(people: dict[str, Session], doc_id: str, spec: dict[str, Any], *, by_email: bool) -> None:
    lead, approver = people["lead"], people[spec["decidedBy"]]

    # A read below the review floor waits for a person to check it before any case opens.
    def doc_ready(d: dict[str, Any]) -> dict[str, Any] | None:
        """Waiting on a person, ended, or past its end while a debtor's case still waits."""
        return (
            d
            if (d.get("waiting") or {}).get("node") in {"check", "ack"} or d["status"] in SETTLED or d.get("outcome")
            else None
        )

    doc = until(lambda: doc_ready(run_detail(lead, doc_id)), seconds=180)
    if doc and (doc.get("waiting") or {}).get("node") == "check":
        decide(approver, doc_id, {"decision": "approved", "reason": spec["checkReason"]})
        say("MADE", "levy notice read check", f"approved by {approver.email}")
        doc = until(lambda: waiting_on(lead, doc_id, "ack") or doc_ready(run_detail(lead, doc_id)), seconds=180)
    if not doc:
        say("FAIL", "levy notice read", f"document run {doc_id} did not reach its acknowledgement")
        return
    records = (step_out(doc, "read") or {}).get("records") or []
    say(
        "FOUND",
        "levy notice read",
        f"{len(records)} debtors: {', '.join(str((r.get('values') or {}).get('name')) for r in records)}",
    )
    children = (step_out(doc, "open") or {}).get("runs") or []
    for child in children:
        settled = run_until(lead, child["runId"], STOPPED)
        if settled is None:
            say("FAIL", "levy case run", f"{child['runId']} still running")
            continue
        name = str(((settled.get("input") or {}).get("record") or {}).get("name"))
        plan = spec["debtors"].get(name, {})
        if plan.get("option") and settled["status"] == "waiting":
            body = {
                "decision": plan["option"],
                "reason": plan["reason"],
                **({"inputs": plan["inputs"]} if plan.get("inputs") else {}),
            }
            decide(approver, child["runId"], body)
            settled = run_until(lead, child["runId"], SETTLED) or run_detail(lead, child["runId"])
            say("MADE", f"levy decision for {name}", f"{plan['option']} by {approver.email}")
        state = settled["status"] if settled["status"] != "succeeded" else f"succeeded/{settled.get('outcome')}"
        say(
            "FOUND" if state == plan.get("expect", state) else "FAIL",
            f"levy case for {name} ends {plan.get('expect', '')}",
            state,
        )
    ending = "replied" if by_email else "cases_opened"
    if (doc.get("waiting") or {}).get("node") == "ack":
        # The reply goes out through the platform's mail sender, whose writes the Platform team approves. An uploaded
        # notice has no mailbox to answer from, so its acknowledgement is declined and the registry is written to.
        replier = people[spec["ackBy"]]
        if by_email:
            decide(replier, doc_id, {"decision": "approved", "reason": spec["ackReason"]})
        else:
            decide(replier, doc_id, {"decision": "rejected", "reason": spec["letterReason"]})

        def replied() -> dict[str, Any] | None:
            d = run_detail(lead, doc_id)
            return d if d.get("outcome") else None

        doc = until(replied) or run_detail(lead, doc_id)
        say("MADE", "levy notice acknowledgement", f"decided by {replier.email}")
    # The notice's run stays open while any debtor's case still waits on a person; its own end is the reply.
    say(
        "FOUND" if doc.get("outcome") == ending else "FAIL",
        f"levy notice ends {ending}",
        f"{doc['status']}/{doc.get('outcome')}",
    )


# ── Cases and their files ────────────────────────────────────────────────────────────────────────────────────────


def pdf(title: str, lines: list[str]) -> bytes:
    """A one-page PDF, the same bytes every run (reportlab's invariant mode), so files-service's dedupe finds it."""
    out = BytesIO()
    page = canvas.Canvas(out, pagesize=A4, invariant=1)
    page.setTitle(title)
    page.setFont("Helvetica-Bold", 14)
    page.drawString(56, 780, title)
    page.setFont("Helvetica", 11)
    for i, line in enumerate(lines):
        page.drawString(56, 750 - i * 18, line)
    page.showPage()
    page.save()
    return out.getvalue()


def find_case(who: Session, subject: str) -> dict[str, Any] | None:
    found = [
        c
        for c in items(data(who("agents").get("/v1/cases", params={"search": subject, "pageSize": 50})))
        if c["subject"] == subject
    ]
    # The newest case still being worked, when the same subject was opened more than once.
    found.sort(key=lambda c: (c["status"] != "closed", c["createdAt"]), reverse=True)
    return found[0] if found else None


def ensure_cases(people: dict[str, Session], spec: dict[str, Any]) -> None:
    """Cases a person opens, and the work people do on the cases the workflows opened: an owner, a status, notes and
    the files that came with them. Each change is made only when the case does not show it yet."""
    for case in spec.get("open", []):
        who = people[case["by"]]
        found = find_case(who, case["subject"])
        if found:
            say("FOUND", f"case {case['subject']}", found["id"])
        else:
            body = {k: case[k] for k in ("subject", "priority", "customerName") if k in case} | {
                "producerKey": f"demo-team:{case['key']}"
            }
            found = data(who("agents").post("/v1/cases", json=body))
            say("MADE", f"case {case['subject']}", found["id"])
        work_on_case(people, found, case)
    for case in spec.get("work", []):
        found = find_case(people[case["by"]], case["subject"])
        if found is None:
            say("FAIL", f"case {case['subject']}", "no workflow opened it")
            continue
        work_on_case(people, found, case)


def work_on_case(people: dict[str, Session], found: dict[str, Any], case: dict[str, Any]) -> None:
    who = people[case["by"]]
    api = who("agents")
    detail = data(api.get(f"/v1/cases/{found['id']}"))
    notes = {str((e.get("detail") or {}).get("text") or "") for e in detail.get("events") or []}
    for note in case.get("notes", []):
        if note not in notes:
            data(api.post(f"/v1/cases/{found['id']}/events", json={"kind": "note", "text": note}))
            say("MADE", f"note on {case['subject']}", note[:60])
    for attachment in case.get("files", []):
        # Stored in Files under the case-attachment purpose. A person has no route that puts a file on a case (file
        # references are written by services only, gap card c-400), so the case's note names it instead.
        file_id = upload(
            who, attachment["name"], pdf(attachment["title"], attachment["lines"]), "application/pdf", "case_attachment"
        )
        say("FOUND", f"file {attachment['name']}", f"{file_id}, not on the case (c-400)")
    patch: dict[str, Any] = {}
    if case.get("assignee") and detail.get("assignee") != people[case["assignee"]].email:
        patch["assignee"] = people[case["assignee"]].email
    if case.get("status") and detail.get("status") != case["status"]:
        patch["status"] = case["status"]
    if patch:
        data(api.patch(f"/v1/cases/{found['id']}", json=patch))
        say("MADE", f"case {case['subject']}", ", ".join(f"{k} {v}" for k, v in patch.items()))


# ── Chats ────────────────────────────────────────────────────────────────────────────────────────────────────────

# Words of the fake model's fallback reply, which means no committed rule answered the turn.
FALLBACK = re.compile(r" heard: | read the tool result")


def send_turn(who: Session, thread_id: str, content: str) -> str:
    """One chat turn, streamed as the console streams it; returns the reply's text."""
    reply = ""
    with who("agents").stream(
        "POST", f"/chat/threads/{thread_id}/messages", json={"content": content}, timeout=180
    ) as r:
        if r.status_code >= 400:
            r.read()
            raise Refused(r)
        for line in r.iter_lines():
            if line.startswith("data:"):
                event = json.loads(line[5:])
                if event.get("type") == "done":
                    reply = str((event.get("message") or {}).get("content") or "")
                elif event.get("type") == "error":
                    raise RuntimeError(f"chat turn failed: {json.dumps(event)[:300]}")
    return reply


def ensure_chats(people: dict[str, Session], chats: list[dict[str, Any]], agents: dict[str, str]) -> None:
    for chat in chats:
        who = people[chat["by"]]
        api = who("agents")
        listed = items(data(api.get("/chat/threads", params={"search": chat["title"]})))
        found = next((t for t in listed if t.get("title") == chat["title"]), None)
        if found and int(found.get("messageCount") or 0) >= 2 * len(chat["turns"]):
            say("FOUND", f"chat {chat['title']}", found["id"])
            continue
        if found:  # an earlier run stopped part way: start the conversation again
            data(api.post("/chat/threads/bulk-delete", json={"ids": [found["id"]]}))
        MODELS.scripted_now()
        thread = data(
            api.post("/chat/threads", json={"agentId": agents[chat["agent"]], "kbIds": [], "title": chat["title"]})
        )
        for turn in chat["turns"]:
            reply = send_turn(who, str(thread["id"]), turn)
            if not reply or FALLBACK.search(reply):
                say("FAIL", f"chat {chat['title']}", f"no scripted reply to {turn[:60]!r}: {reply[:120]!r}")
                break
        else:
            say("MADE", f"chat {chat['title']}", f"{thread['id']}, {len(chat['turns'])} turns")


# ── Runs and Human Task decisions ────────────────────────────────────────────────────────────────────────────────

SETTLED = {"succeeded", "failed", "cancelled"}
# Stopped: ended, or waiting on a person.
STOPPED = SETTLED | {"waiting"}


def run_until(who: Session, run_id: str, states: set[str]) -> dict[str, Any] | None:
    """The run once its status is one of `states`, or None after the wait."""

    def probe() -> dict[str, Any] | None:
        run = run_detail(who, run_id)
        return run if run["status"] in states else None

    return until(probe)


def decide(who: Session, review_id: str, body: dict[str, Any]) -> Any:
    """A Human Task decision; a step whose approval policy asks for a step-up gets one first, as the console's
    re-authenticate dialog does."""
    r = who("agents").post(f"/reviews/{review_id}/decision", json=body)
    owner = approving_team(r)
    if owner and owner != who.team and ADMIN:
        # The operation's writes are approved by the team that owns its tool module (team_ops locally, the Security
        # team on staging): the approver joins it with the same role, as a workspace admin would arrange.
        join_team(ADMIN[0], who, owner, "approver")
        r = who("agents").post(f"/reviews/{review_id}/decision", json=body)
    if r.status_code == 422 and Refused(r).code == "step_up_required":
        stepped = data(who("platform").post("/v1/auth/step-up", json={"password": who.password}))
        r = who("agents").post(f"/reviews/{review_id}/decision", json={**body, "stepUpToken": stepped["token"]})
    return data(r)


def run_detail(who: Session, run_id: str) -> dict[str, Any]:
    return data(who("agents").get(f"/v1/runs/{run_id}"))


def ensure_runs(people: dict[str, Session], runs: list[dict[str, Any]], names: dict[str, str]) -> None:
    for spec in runs:
        who = people[spec["by"]]
        workflow = names.get(f"workflow:{spec['workflow']}", spec["workflow"])
        # A run made before is found by its input, so the agents are not moved to the scripted alias for nothing.
        made = [r for r in runs_of(who, workflow) if r.get("mode") == "live" and r.get("input") == spec["input"]]
        if not made:
            MODELS.scripted_now()
        started = data(
            who("agents").post(
                "/v1/runs",
                json={
                    "workflowId": workflow,
                    "runKey": f"demo-team:{spec['key']}",
                    "input": spec["input"],
                },
            )
        )
        run_id = str(started["runId"])
        say("MADE" if started.get("created") else "FOUND", f"run {spec['title']}", run_id)
        run = run_until(who, run_id, STOPPED)
        if run is None:
            say("FAIL", f"run {spec['title']}", "still running after two minutes (is the workflow worker up?)")
            continue
        decision = spec.get("decision")
        if decision and run["status"] == "waiting":
            approver = people[decision["by"]]
            decide(approver, run_id, {"decision": decision["decision"], "reason": decision["reason"]})
            run = run_until(who, run_id, SETTLED) or run_detail(who, run_id)
            say("MADE", f"decision on {spec['title']}", f"{decision['decision']} by {approver.email}")
        expected = spec["expect"]
        state = run["status"] if run["status"] != "succeeded" else f"succeeded/{run.get('outcome')}"
        ok = state == expected or run["status"] == expected
        say(
            "FOUND" if ok else "FAIL",
            f"run {spec['title']} ends {expected}",
            state if ok else f"{state}: {run.get('error') or ''}",
        )


def prefixed(spec: dict[str, Any], prefix: str) -> None:
    """Every workflow and document type the team makes under `prefix` + its id, with the workflows and types each
    workflow names and the runs that name it following, so the team's copies never meet another team's ids: both
    kinds of id are unique in the workspace and belong to the first team that makes one (c-440)."""
    ids: dict[str, str] = {}
    for wf in spec["workflows"]:
        own = wf.get("id") or json.loads((HERE / "workflows" / wf["file"]).read_text())["id"]
        ids[own] = wf["id"] = f"{prefix}{own}"
    kinds: dict[str, str] = {}
    for kind in spec["documentTypes"]:
        kinds[kind["id"]] = kind["id"] = f"{prefix}{kind['id']}"
    for wf in spec["workflows"]:
        if "workflows" in wf:
            wf["workflows"] = {k: ids.get(v, v) for k, v in wf["workflows"].items()}
        if "documentTypes" in wf:
            wf["documentTypes"] = {k: kinds.get(v, v) for k, v in wf["documentTypes"].items()}
    for run in spec["runs"]:
        run["workflow"] = ids.get(run["workflow"], run["workflow"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origin", required=True, help="the install's public address, such as http://localhost:3016")
    ap.add_argument(
        "--admin-env",
        required=True,
        type=Path,
        help="file with OPS_DEMO_ADMIN_EMAIL and OPS_DEMO_ADMIN_PASSWORD (or OPS_BOOTSTRAP_ADMIN_*)",
    )
    ap.add_argument(
        "--people-env",
        type=Path,
        help="file with OPS_DEMO_PASSWORD and the other OPS_DEMO_* settings; default --admin-env. A missing password "
        "is generated into it",
    )
    ap.add_argument("--team", help="the team's name, in place of team.json's (a fresh team for a clean demo)")
    ap.add_argument(
        "--member",
        action="append",
        default=[],
        metavar="EMAIL:ROLE",
        help="a person outside team.json who joins the team with ROLE; repeatable. Their password is in the "
        "environment variable --member-password-env names",
    )
    ap.add_argument("--member-password-env", default="OPS_DEMO_MEMBER_PASSWORD")
    ap.add_argument(
        "--workflow-prefix",
        default="",
        help="put before every workflow and document type id the team makes: each id belongs to the first team that "
        "makes it, so a second demo team in one workspace needs its own ids",
    )
    ap.add_argument(
        "--tool-access",
        action="append",
        default=[],
        metavar="MODULE_ID",
        help="a tool module another team owns that the team's workflows are granted; repeatable",
    )
    ap.add_argument("--tool-access-team", help="the team that owns the --tool-access modules and decides the grants")
    ap.add_argument("--tool-approver", help="a person who decides that team's tool access requests")
    ap.add_argument("--tool-approver-password-env", default="OPS_DEMO_TOOL_APPROVER_PASSWORD")
    ap.add_argument(
        "--extras",
        action="store_true",
        help="also make team_extras.json: the team's skills and guardrails, published, and its default chat agent",
    )
    ap.add_argument(
        "--no-levy",
        action="store_true",
        help="leave out the levy notice story and its workflows: its read runs on the documents model, which is a real "
        "one on staging; the levy walk (docs/console/mailbox-demo.md) makes that story and its workflows instead",
    )
    args = ap.parse_args()
    env = read_env(args.admin_env)
    # An install's bootstrap file (deploy/images/first_admin.sh) names its first admin under OPS_BOOTSTRAP_*.
    for name in ("EMAIL", "PASSWORD"):
        env.setdefault(f"OPS_DEMO_ADMIN_{name}", env.get(f"OPS_BOOTSTRAP_ADMIN_{name}", ""))
    people_env = args.people_env or args.admin_env
    env |= {k: v for k, v in read_env(people_env).items() if k.startswith("OPS_DEMO_")} if people_env.exists() else {}
    if not env.get("OPS_DEMO_PASSWORD"):
        # Generated once into the people file (mode 600) and never printed; the capture script reads it from there.
        env["OPS_DEMO_PASSWORD"] = f"nf-{uuid.uuid4().hex[:20]}"
        with people_env.open("a") as out:
            out.write(f"OPS_DEMO_PASSWORD={env['OPS_DEMO_PASSWORD']}\n")
        people_env.chmod(0o600)
        say("MADE", "demo people's password", f"kept in {people_env}")
    missing = [k for k in ("OPS_DEMO_ADMIN_EMAIL", "OPS_DEMO_ADMIN_PASSWORD") if not env.get(k)]
    if missing:
        raise SystemExit(f"seed: {args.admin_env} has no {', '.join(missing)}")
    spec = json.loads(TEAM_FILE.read_text())
    if args.team:
        spec["team"]["name"] = args.team
    if args.workflow_prefix:
        prefixed(spec, args.workflow_prefix)
    members = [tuple(m.rsplit(":", 1)) for m in args.member]
    if members and not os.environ.get(args.member_password_env):
        raise SystemExit(f"seed: --member needs the members' password in {args.member_password_env}")
    urls = service_urls(args.origin)
    admin = sign_in(urls, env["OPS_DEMO_ADMIN_EMAIL"], env["OPS_DEMO_ADMIN_PASSWORD"])
    team = ensure_team(admin, spec["team"])
    # A token names the teams its person was in when it was issued; sign in again to act in the new team.
    admin = sign_in(urls, env["OPS_DEMO_ADMIN_EMAIL"], env["OPS_DEMO_ADMIN_PASSWORD"], team)
    people = ensure_people(admin, team, spec["people"], env["OPS_DEMO_PASSWORD"])
    if members:
        ensure_members(admin, team, [(e, r) for e, r in members], os.environ[args.member_password_env])
    people["admin"] = admin
    ADMIN.append(admin)
    lead, builder = people["lead"], people["builder"]
    knowledge = ensure_knowledge(builder, spec["knowledge"])
    model = env.get("OPS_DEMO_MODEL_ALIAS") or "default"
    MODELS.scripted, MODELS.live = model, env.get("OPS_DEMO_LIVE_MODEL_ALIAS") or None
    MODELS.builder, MODELS.approver = builder, people["approver"]
    agents = ensure_agents(builder, people["approver"], spec["agents"], knowledge, model)
    MODELS.agents = agents
    names = {f"agent:{k}": v for k, v in agents.items()}
    ensure_document_types(builder, spec["documentTypes"])
    mailbox = ensure_mailbox(admin, lead, env, spec["mailbox"])
    ensure_workflows(builder, people["approver"], team_workflows(spec, no_levy=args.no_levy), names, mailbox)
    if args.tool_access:
        if not (args.tool_access_team and args.tool_approver and os.environ.get(args.tool_approver_password_env)):
            raise SystemExit("seed: --tool-access needs --tool-access-team, --tool-approver and its password")
        approver = sign_in(urls, args.tool_approver, os.environ[args.tool_approver_password_env])
        why = "The team's workflows read customers and accounts and write holds and replies through these tools."
        ensure_tool_access(
            admin, team, owning_team=args.tool_access_team, modules=args.tool_access, approver=approver, why=why
        )
    ensure_runs(people, spec["runs"], names)
    if args.no_levy:
        say("SKIP", "levy notice story", "--no-levy")
    else:
        ensure_levy_mail(people, env, mailbox, spec["levyMail"])
    ensure_cases(people, spec["cases"])
    ensure_chats(people, spec["chats"], agents)
    if args.extras:
        ensure_extras(people, agents, json.loads(EXTRAS_FILE.read_text()))
    MODELS.live_now()
    print(f"\n{len(FAILED)} failed", flush=True)
    return len(FAILED)


if __name__ == "__main__":
    sys.exit(main())
