"""Installs the sample team on an Ops AI install through its public HTTP API only (c-542; from c-383's demo seed).

    make sample-team                          the local stack, signed in as the first admin in .run/dev-admin.env
    uv run python scripts/sample_team.py install [--name NAME] [--origin URL] [--admin-env FILE]

Everything installed is listed in one manifest, scripts/sample-team/sample-team.json: the team, its people, the
templates it installs, its knowledge, the fakes (the model alias, the bank key and the egress entries), skills,
guardrails, agents, code modules, document types, the mailbox and the workflows, in that order. Workflow definitions and
function code are files in scripts/sample-team/ that the manifest names by path.

`--origin` is the install's public address: one that serves `/api/<service>/` (deploy/fly/Caddyfile) is used as it is;
a local console origin reaches each service on its own port (OPS_<SERVICE>_PORT). `--admin-env` names a file of
KEY=value lines with a workspace admin's email and password (OPS_BOOTSTRAP_ADMIN_* or OPS_DEMO_ADMIN_*); the people's
password (OPS_DEMO_PASSWORD) is generated into it on the first run and never printed.

Each record is looked up by name or key before it is made, so a second run finds everything and makes nothing. Every
line says MADE, FOUND, SKIP or FAIL, and the exit status is the number of FAIL lines. `--name` installs a second team
in the same workspace, with its workflow and document type ids prefixed, since each of those ids belongs to the first
team that makes it.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from dev_egress import HOSTS, host_ip, private_address

from ops_identity import mint_service_token
from ops_identity.service_keys import dev_service_signer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SAMPLE = HERE / "sample-team"
MANIFEST = SAMPLE / "sample-team.json"
WORKFLOWS = SAMPLE / "workflows"
CODE = SAMPLE / "code"
# The manifest's sections, in install order; a section not listed here is refused, so a typo never installs nothing.
SECTIONS = (
    "team",
    "people",
    "templates",
    "knowledge",
    "fakes",
    "skills",
    "guardrails",
    "agents",
    "codeModules",
    "documentTypes",
    "mailbox",
    "workflows",
)
SERVICES = ("platform", "agents", "tools", "kb", "files", "documents")
# The team that decides tool module publish reviews: a workspace's own security team.
SECURITY_TEAM = os.environ.get("OPS_DEMO_SECURITY_TEAM", "team_security")
LOCAL_PORTS = {"platform": 8710, "agents": 8700, "tools": 8720, "kb": 8740, "files": 8750, "documents": 8760}
WAIT_S = 120.0

FAILED: list[str] = []


# `--expect-found`: a run after an install makes nothing, so a MADE line there is a failure.
EXPECT_FOUND: list[bool] = []


def say(state: str, what: str, detail: str = "") -> None:
    if state == "MADE" and EXPECT_FOUND:
        state, detail = "FAIL", f"made on a run that expected to find everything; {detail}"
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
        same = [b for b in listed if b["name"].lower() == base["name"].lower()]
        # This team's copy first; an unowned handbook with the same name is visible here and blocks a second
        # create, so the seed reuses it rather than 409 (c-532).
        found = next((b for b in same if b.get("teamId") == who.team), None) or next(
            (b for b in same if not b.get("teamId")), None
        )
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


# The bank's own document, served by the fake bank on the stack (tools-service reaches it through its egress list).
BANK_HOST = os.environ.get("OPS_DEMO_BANK_HOST", "api.bank.test")
BANK_MODULE = "northfield-core-banking"


def ensure_bank_module(builder: Session, admin: Session) -> None:
    """The team's own copy of the bank system: its OpenAPI document imported as a module the team owns, published
    through the workspace's Security team as any module is. A team uses only modules it owns (team = workspace: sharing
    is installing a copy), so the agents and workflows that read customers and accounts need it before they are made.
    Reads come from GET; place_hold needs one approver of the team with a step-up; the levy webhook runs at once."""
    api = builder("tools")
    listed = items(data(api.get("/v1/tool-modules", params={"search": BANK_MODULE, "pageSize": 50})))
    # The list is this team's: a published module of the same name another team holds is not here (c-509).
    found = next((m for m in listed if m["name"] == BANK_MODULE and m.get("status") == "published"), None)
    if found is not None:
        say("FOUND", "bank module", str(found["id"]))
        return
    source = {"kind": "openapi", "specUrl": f"https://{BANK_HOST}/openapi.json"}
    try:
        doc = data(api.post("/v1/tool-modules/discover", json=source))
        operations = [
            {**o, "access": "read" if (o.get("method") or "GET").upper() == "GET" else "write"}
            for o in doc["operations"]
        ]
        draft = next((m for m in listed if m["name"] == BANK_MODULE), None)
        made = draft or data(
            api.post(
                "/v1/tool-modules",
                json={
                    "name": BANK_MODULE,
                    "displayName": "Northfield Core Banking",
                    "system": doc["system"],
                    "type": "openapi",
                    "endpoint": doc["endpoint"],
                    "operations": operations,
                    "source": source,
                },
            )
        )
        module = data(api.get(f"/v1/tool-modules/{made['id']}"))
        for op in module["operations"]:
            if op["name"] == "place_hold":
                policy = {"approvers": 1, "approverTeam": builder.team, "requiresApproval": True, "stepUp": True}
                data(api.patch(f"/v1/tool-modules/{made['id']}/operations/{op['id']}", json=policy))
            elif op["name"] == "notify_webhook":
                data(
                    api.patch(
                        f"/v1/tool-modules/{made['id']}/operations/{op['id']}",
                        json={"requiresApproval": False},
                    )
                )
        data(api.post(f"/v1/tool-modules/{made['id']}/reviews", json={"note": "The team's copy of the bank system."}))
        waiting = next(
            v for v in data(api.get(f"/v1/tool-modules/{made['id']}"))["versions"] if v["status"] == "in_review"
        )
        security_team = str(data(admin("platform").get("/v1/me"))["securityTeamId"])
        security = sign_in(admin.urls, admin.email, admin.password, security_team)
        decided = security("agents").post(
            f"/v1/publish-requests/{waiting['reviewId']}/decision",
            json={"decision": "approved", "reason": "The bank's own document, copied for the team."},
        )
        say("MADE" if decided.status_code < 300 else "FAIL", "bank module", f"{made['id']} {decided.status_code}")
    except Refused as e:
        say("FAIL", "bank module", str(e))


def ensure_agents(
    builder: Session,
    approver: Session,
    agents: list[dict[str, Any]],
    knowledge: dict[str, str],
    model: str,
    *,
    pins: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    """Each agent with its instructions, tools, knowledge, skills and guardrails, published. A published agent that
    differs from the manifest gets a new version, published the same way. `pins` holds the skill and guardrail ids by
    name, under "skills" and "guardrails"."""
    pins = pins or {"skills": {}, "guardrails": {}}
    api = builder("agents")
    ids: dict[str, str] = {}
    for agent in agents:
        skill_ids = sorted(pins["skills"][n] for n in agent.get("skills", []))
        wanted = {
            "role": agent["role"],
            "instructions": agent["instructions"],
            "model": model,
            "toolIds": agent["tools"],
            "collections": [knowledge[k] for k in agent["knowledge"]],
            # Memory writes a line per turn through its own model alias; the sample's turns are scripted.
            "memory": {"enabled": False},
            "guardrailPins": sorted(pins["guardrails"][n] for n in agent.get("guardrails", [])),
        }
        listed = items(data(api.get("/v1/agents", params={"search": agent["name"], "pageSize": 50})))
        found = next((a for a in listed if a["name"] == agent["name"] and a.get("teamId") == builder.team), None)
        if found:
            detail = data(api.get(f"/v1/agents/{found['id']}"))
            have = {k: detail.get(k) for k in wanted} | {
                "memory": {"enabled": bool((detail.get("memory") or {}).get("enabled"))},
                "guardrailPins": sorted(str(g["guardrailId"]) for g in detail.get("guardrailPins") or []),
            }
            held = sorted(str(x["skillId"]) for x in data(api.get(f"/v1/agents/{found['id']}/skills"))["pins"])
            # An agent the last run moved to the live alias (OPS_DEMO_LIVE_MODEL_ALIAS) is as the manifest wants it.
            if have["model"] in MODELS.accepted:
                have["model"] = model
            if detail.get("publishedVersion") and have == wanted and held == skill_ids:
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
            held = []
            say("MADE", f"agent {agent['name']}", str(found["id"]))
        body = {k: v for k, v in wanted.items() if k != "guardrailPins"}
        body["guardrailPins"] = [{"guardrailId": g} for g in wanted["guardrailPins"]]
        note = agent.get("note", "Instructions, tools, knowledge, skills and guardrails for the team.")
        data(api.patch(f"/v1/agents/{found['id']}", json={**body, "note": note}))
        for sid in skill_ids:
            if sid not in held:
                data(api.put(f"/v1/agents/{found['id']}/skills/{sid}", json={}))
        version = data(api.get(f"/v1/agents/{found['id']}"))["version"]
        review = data(
            api.post(
                f"/v1/agents/{found['id']}/publish-requests",
                json={"version": version, "note": "Release for the team."},
            )
        )
        decide_publish(approver, review, f"agent {agent['name']} v{version}")
        ids[agent["key"]] = str(found["id"])
    return ids


# ── Document types ───────────────────────────────────────────────────────────────────────────────────────────────

SEEDED_DOCUMENT_TYPES = ROOT / "services" / "documents-service" / "scripts" / "seed_document_types.py"


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


def ensure_team_secret(admin: Session, team_id: str, name: str, value: str) -> None:
    """A Secrets-page secret in `team_id`, as a Security admin creates one (POST /v1/secrets with teamId). A name
    already there is left; its value never comes back, so it is not compared."""
    security_team = str(data(admin("platform").get("/v1/settings/workspace-teams"))["securityTeam"])
    security = sign_in(admin.urls, admin.email, admin.password, security_team)
    theirs = items(data(security("tools").get(f"/v1/secrets?teamId={team_id}")))
    if any(x["name"] == name for x in theirs):
        say("FOUND", f"secret {name}")
        return
    data(security("tools").post("/v1/secrets", json={"name": name, "value": value, "teamId": team_id}))
    say("MADE", f"secret {name}", f"for team {team_id}")


def ensure_mailbox(admin: Session, lead: Session, env: dict[str, str], spec: dict[str, Any]) -> str | None:
    """The team's legal orders mailbox on Channels > Email, as an admin connects one: its password a Secrets-page
    secret only the team may use (set by a Security admin), then Test connection."""
    # The manifest's hosts are the dev mail fakes; OPS_DEMO_* in the env file names another install's servers.
    address = env.get("OPS_DEMO_MAILBOX") or spec.get("address")
    if not address:
        say("SKIP", "mailbox", "no address in the manifest or OPS_DEMO_MAILBOX")
        return None
    imap_host, imap_port = hostport(env.get("OPS_DEMO_IMAP") or spec["imap"])
    smtp_host, smtp_port = hostport(env.get("OPS_DEMO_REPLY_SMTP") or spec["replySmtp"])
    tls = env["OPS_DEMO_MAIL_TLS"] != "0" if "OPS_DEMO_MAIL_TLS" in env else bool(spec.get("tls"))
    secret = spec["secret"]
    # The secret is the lead's team's own (c-509); a Security admin writes and reads it by naming that team.
    ensure_team_secret(admin, str(lead.team), secret, env.get("OPS_DEMO_MAILBOX_PASSWORD") or uuid.uuid4().hex)
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
    """`{agent:<key>}`, `{workflow:<key>}` and `{documentType:<id>}` in a definition file name a record this run made:
    an agent by its key, a workflow by its team.json key, a document type by its team.json id."""
    if isinstance(value, str):
        pattern = r"\{(agent|workflow|documentType):(\w+)\}"
        return re.sub(pattern, lambda m: names[f"{m.group(1)}:{m.group(2)}"], value)
    if isinstance(value, list):
        return [placeholders(v, names) for v in value]
    if isinstance(value, dict):
        return {k: placeholders(v, names) for k, v in value.items()}
    return value


def same_definition(stored: dict[str, Any], wanted: dict[str, Any]) -> bool:
    """Whether the stored version is the file's, read as numbers (the service stores positions as floats). A node the
    file gives no position is laid out by the service, so its stored position is not compared."""
    keys = ("name", "description", "nodes", "connections")
    unplaced = {n["id"] for n in wanted.get("nodes") or [] if "position" not in n}
    stored = stored | {
        "nodes": [
            {k: v for k, v in n.items() if not (k == "position" and n["id"] in unplaced)}
            for n in stored.get("nodes") or []
        ]
    }

    def plain(d: dict[str, Any]) -> str:
        return json.dumps(json.loads(json.dumps({k: d.get(k) for k in keys}), parse_int=float), sort_keys=True)

    return plain(stored) == plain(wanted)


SEEDED_WORKFLOWS = ROOT / "services" / "agents-service" / "seed" / "engine_workflows.json"


def definition_of(wf: dict[str, Any], names: dict[str, str], mailbox: str | None) -> dict[str, Any]:
    """The team's copy of a workflow: its own file under workflows/, or a seeded workflow (`seed`) under the team's id
    and name, with the workflows it starts renamed to the team's copies and its email trigger on the team's mailbox."""
    if "file" in wf:
        own = placeholders(json.loads((WORKFLOWS / wf["file"]).read_text()), names)
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
    """Whether a team.json workflow belongs to the levy story: a copy of a seeded levy workflow, or a file marked
    `story: levy`, which deploy/fly/staging/mailbox_demo.py levy makes under the team's own ids."""
    return "seed" in wf or wf.get("story") == "levy"


def ids_by_key(spec: dict[str, Any]) -> dict[str, str]:
    """The placeholder names of the team's workflows (by team.json key) and document types (by their unprefixed id),
    each to the id the team makes it under."""
    out = {f"workflow:{wf['key']}": wf["id"] for wf in spec["workflows"] if "id" in wf}
    return out | {f"documentType:{k.get('key') or k['id']}": k["id"] for k in spec["documentTypes"]}


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
        asked = api.post(
            f"/v1/workflows/definitions/{wid}/publish-requests", json={"note": "First release for the team."}
        )
        if asked.status_code == 409 and Refused(asked).code == "not_a_draft":
            # The seed's version is one the team had before; a later one someone published stays live.
            say("NOTE", f"workflow {definition['name']}", f"{wid}: a later version is live and is left as it is")
            continue
        decide_publish(approver, data(asked), f"workflow {definition['name']}")


def ensure_code_modules(builder: Session, security: Session, modules: list[dict[str, Any]]) -> None:
    """Each code tool module (c-531), its function's source read from code/ beside this script, made by the builder
    and published through Security's review as any module is. A module of that name already in the team is FOUND and
    left as it is."""
    api = builder("tools")
    for spec in modules:
        listed = items(data(api.get("/v1/tool-modules", params={"search": spec["name"], "pageSize": 50})))
        found = next((m for m in listed if m["name"] == spec["name"]), None)
        if found is not None and found.get("status") == "published":
            say("FOUND", f"code module {spec['displayName']}", str(found["id"]))
            continue
        fn = spec["function"]
        source = (CODE / fn["code"]["file"]).read_text()
        body = {k: v for k, v in spec.items() if k not in ("key", "function")} | {
            "type": "code",
            "endpoint": "",
            "function": fn | {"code": {k: v for k, v in fn["code"].items() if k != "file"} | {"source": source}},
        }
        module = found or data(api.post("/v1/tool-modules", json=body))
        say("MADE" if found is None else "FOUND", f"code module {spec['displayName']}", str(module["id"]))
        data(api.post(f"/v1/tool-modules/{module['id']}/reviews", json={"note": "The demo team's levy rules."}))
        waiting = next(
            v for v in data(api.get(f"/v1/tool-modules/{module['id']}"))["versions"] if v["status"] == "in_review"
        )
        decided = security("agents").post(
            f"/v1/publish-requests/{waiting['reviewId']}/decision",
            json={"decision": "approved", "reason": "Checked the function, its one bound read and its secret."},
        )
        say(
            "MADE" if decided.status_code < 300 else "FAIL",
            f"code module {spec['displayName']} publish",
            str(decided.status_code),
        )


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


def ensure_skills(builder: Session, approver: Session, skills: list[dict[str, Any]]) -> dict[str, str]:
    """The team's skills, each published through review; found by name before it is made. Answers name to id, for
    the agents that pin them."""
    api = builder("agents")
    have = {s["name"]: s for s in items(data(api.get("/v1/skills", params={"pageSize": 100})))}
    ids: dict[str, str] = {}
    for skill in skills:
        found = have.get(skill["name"]) or data(api.post("/v1/skills", json=skill))
        sid = ids[skill["name"]] = str(found["id"])
        detail = data(api.get(f"/v1/skills/{sid}"))
        if detail.get("publishedVersion") is not None:
            say("FOUND", f"skill {skill['name']}", f"{sid} published")
            continue
        if not detail.get("pendingReviewId"):
            detail = data(api.post(f"/v1/skills/{sid}/publish-requests", json={"note": "For the team."}))
        # A skill's publish answers the skill; its open request is `pendingReviewId`, none when it went live at once.
        pending = detail.get("pendingReviewId")
        decide_publish(approver, {"id": pending} if pending else {"status": "published"}, f"skill {skill['name']}")
    return ids


def ensure_guardrails(builder: Session, approver: Session, rules: list[dict[str, Any]]) -> dict[str, str]:
    """The team's guardrails, each published through review; found by name before it is made. Answers name to id."""
    api = builder("agents")
    have = {g["name"]: g for g in items(data(api.get("/v1/guardrails", params={"pageSize": 100})))}
    ids: dict[str, str] = {}
    for rule in rules:
        found = have.get(rule["name"]) or data(api.post("/v1/guardrails", json=rule))
        gid = ids[rule["name"]] = str(found["id"])
        if found.get("publishedVersion") is not None:
            say("FOUND", f"guardrail {rule['name']}", f"{gid} published")
            continue
        if not found.get("pendingRequestId"):
            body = {"version": found.get("version") or 1, "note": "For the team."}
            found = data(api.post(f"/v1/guardrails/{gid}/publish-requests", json=body))
        pending = found.get("pendingRequestId")
        decide_publish(approver, {"id": pending} if pending else {"status": "published"}, f"guardrail {rule['name']}")
    return ids


def ensure_default_agent(admin: Session, agents: dict[str, str], key: str | None) -> None:
    if not key or key not in agents:
        return
    found = data(admin("agents").get("/chat/default-agent"))
    if found.get("agentId") == agents[key]:
        say("FOUND", "default chat agent", agents[key])
    else:
        data(admin("agents").put("/chat/default-agent", json={"agentId": agents[key]}))
        say("MADE", "default chat agent", agents[key])


# ── Manifest, templates and fakes ────────────────────────────────────────────────────────────────────────────────


def check_manifest(spec: dict[str, Any]) -> None:
    """Refuses a manifest with a section this installer does not know or without one it needs."""
    given = {k for k in spec if not k.startswith("$")}
    unknown, missing = sorted(given - set(SECTIONS)), sorted(set(SECTIONS) - given)
    if unknown or missing:
        raise SystemExit(f"sample-team: {MANIFEST.name}: unknown sections {unknown}, missing sections {missing}")


TEMPLATE_READS = {"caseType": "/v1/case-types/{id}", "taskType": "/v1/task-types/{id}"}


def ensure_templates(builder: Session, templates: list[dict[str, Any]]) -> None:
    """The built-in types the team installs from templates (c-541). Until the install routes exist, each type is one
    every team reads already, so it is checked rather than made."""
    api = builder("agents")
    installable = api.get("/v1/templates").status_code == 200
    for t in templates:
        what = f"template {t['kind']} {t['id']}"
        if installable:
            r = api.post("/v1/templates/install", json={"kind": t["kind"], "id": t["id"], "version": t["version"]})
            if r.status_code == 409:
                say("FOUND", what, f"v{t['version']}")
            else:
                data(r)
                say("MADE", what, f"v{t['version']}")
            continue
        read = api.get(TEMPLATE_READS[t["kind"]].format(id=t["id"]))
        if read.status_code == 200:
            say("FOUND", what, "built in")
        else:
            say("FAIL", what, f"not readable ({read.status_code}) and no template install route (c-541)")


FAKE_PROVIDER = "fake-demo"
# Priced as a small hosted model, so the call log's cost column reads as it would for a real one.
FAKE_PRICE = {"inputPerMillion": "0.25", "outputPerMillion": "2.00"}


def local(admin: Session) -> bool:
    return httpx.URL(admin.urls["platform"]).host in {"127.0.0.1", "localhost"}


def ensure_fake_aliases(fakes: dict[str, Any]) -> None:
    """The alias the team's agents name, served by the stack's fake model (its committed rules answer each alias by
    name), through models-service's own admin routes with a dev service token. The aliases the guardrail checks,
    memory and document reads use join it only when MODEL is `fake` (make sample-team passes make up's DEMO_MODEL), so
    a stack whose reads run on a real model keeps them there."""
    model = os.environ.get("MODEL") or "fake"
    port = os.environ.get("OPS_MODELS_PORT", "8730")
    fake_url = f"http://127.0.0.1:{os.environ.get('OPS_FAKE_OPENAI_PORT', '8746')}/v1"
    token = mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id="team_ops")
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"Authorization": f"Bearer {token}"}) as m:
        providers = items(data(m.get("/v1/models/providers")))
        found = next((p for p in providers if FAKE_PROVIDER in (p["id"], p.get("name"))), None)
        if found is None:
            body = {"name": FAKE_PROVIDER, "type": "openai-compatible", "baseUrl": fake_url}
            found = data(m.post("/v1/models/providers", json=body))
            say("MADE", f"model provider {FAKE_PROVIDER}", fake_url)
        elif found.get("baseUrl") != fake_url:
            data(m.put(f"/v1/models/providers/{found['id']}", json={"baseUrl": fake_url, "keyRef": None}))
            say("MADE", f"model provider {FAKE_PROVIDER}", f"moved to {fake_url}")
        else:
            say("FOUND", f"model provider {FAKE_PROVIDER}", fake_url)
        provider = str(found["id"])
        aliases = [fakes["modelAlias"]]
        if model == "fake":
            aliases += fakes.get("modelAliases", [])
        else:
            say("SKIP", "model aliases " + ", ".join(fakes.get("modelAliases", [])), f"MODEL={model}: left as they are")
        for alias in aliases:
            versions = m.get(f"/v1/models/aliases/{alias}/versions")
            wanted = {"providerId": provider, "modelId": alias, "clearedSensitivity": "restricted", **FAKE_PRICE}
            if versions.status_code == 404:
                data(m.post("/v1/models/aliases", json={"name": alias, "kind": "chat", **wanted}))
                say("MADE", f"model alias {alias}", f"on {FAKE_PROVIDER}")
                continue
            current = data(versions)[-1]
            if (current["providerId"], current["modelId"]) == (provider, alias):
                say("FOUND", f"model alias {alias}", f"v{current['version']} on {FAKE_PROVIDER}")
                continue
            wanted["clearedSensitivity"] = current["clearedSensitivity"]
            made = data(m.post(f"/v1/models/aliases/{alias}/versions", json=wanted))
            say("MADE", f"model alias {alias}", f"v{made['version']} on {FAKE_PROVIDER}")


def ensure_egress(admin: Session, fakes: dict[str, Any]) -> None:
    """The fake bank and the dev mail hosts on the workspace's egress list, with the addresses tools-service reaches
    them at: this machine's private address, or a side container's (devcontainer)."""
    security_team = str(data(admin("platform").get("/v1/settings/workspace-teams"))["securityTeam"])
    tools = sign_in(admin.urls, admin.email, admin.password, security_team)("tools")
    have = data(tools.get("/v1/egress"))
    hosts, ranges = {x["host"] for x in have["hosts"]}, {x["cidr"] for x in have["ranges"]}
    wanted = [("hosts", host, note) for host, note in HOSTS.items()]
    wanted.append(("ranges", f"{private_address()}/32", "this machine's address, for the dev mail and bank fakes"))
    for env, label in ((fakes["mail"]["greenmailEnv"], "greenmail"), (fakes["mail"]["mailpitEnv"], "mailpit")):
        if addr := host_ip(os.environ.get(env, "")):
            wanted.append(("ranges", f"{addr}/32", f"{label} side container"))
    if addr := host_ip(os.environ.get(fakes["bank"]["hostEnv"]) or fakes["bank"]["host"]):
        wanted.append(("ranges", f"{addr}/32", "fake bank side container"))
    for kind, value, note in wanted:
        if value in (hosts if kind == "hosts" else ranges):
            say("FOUND", f"egress {value}")
            continue
        data(tools.post(f"/v1/egress/{kind}", json={"value": value, "note": note}))
        say("MADE", f"egress {value}", note)


def ensure_fakes(admin: Session, lead: Session, fakes: dict[str, Any]) -> None:
    """The fake model's aliases, the fake bank's key as the team's secret and the egress entries. On a remote install
    only the secret is set: its aliases and egress list are its operators'."""
    ensure_team_secret(
        admin, str(lead.team), fakes["bank"]["secret"], os.environ.get("FAKE_BANK_KEY") or "dev-bank-key"
    )
    if not local(admin):
        say("SKIP", "model aliases and egress", "not a local stack")
        return
    ensure_fake_aliases(fakes)
    ensure_egress(admin, fakes)


# ── Runs and Human Task decisions (deploy/fly/staging/mailbox_demo.py uses these) ─────────────────────────────


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


def prefixed(spec: dict[str, Any], prefix: str) -> None:
    """Every workflow and document type the team makes under `prefix` + its id, with the workflows and types each
    workflow names following, so the team's copies never meet another team's ids: both kinds of id are unique in the
    workspace and belong to the first team that makes one (c-440)."""
    ids: dict[str, str] = {}
    for wf in spec["workflows"]:
        own = wf.get("id") or json.loads((WORKFLOWS / wf["file"]).read_text())["id"]
        ids[own] = wf["id"] = f"{prefix}{own}"
    kinds: dict[str, str] = {}
    for kind in spec["documentTypes"]:
        kind.setdefault("key", kind["id"])
        kinds[kind["id"]] = kind["id"] = f"{prefix}{kind['id']}"
    for wf in spec["workflows"]:
        if "workflows" in wf:
            wf["workflows"] = {k: ids.get(v, v) for k, v in wf["workflows"].items()}
        if "documentTypes" in wf:
            wf["documentTypes"] = {k: kinds.get(v, v) for k, v in wf["documentTypes"].items()}


def named(spec: dict[str, Any], team: str) -> None:
    """A second team's skills, guardrails and mailbox under its own names, with its agents' pins following: a skill's
    slug, made from its name, and a mailbox address are each unique in the workspace."""
    local, _, domain = spec["mailbox"]["address"].partition("@")
    spec["mailbox"]["address"] = f"{prefix_of(team).strip('_').replace('_', '-')}-{local}@{domain}"
    for kind in ("skills", "guardrails"):
        renamed = {r["name"]: f"{team}: {r['name']}" for r in spec[kind]}
        for r in spec[kind]:
            r["name"] = renamed[r["name"]]
        for agent in spec["agents"]:
            agent[kind] = [renamed[n] for n in agent.get(kind, [])]


def prefix_of(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") + "_"


def admin_env(path: Path) -> dict[str, str]:
    """The admin's email and password and the people's settings from `path`; the people's password is generated into
    it (mode 600) on the first run and never printed."""
    if not path.exists():
        raise SystemExit(f"sample-team: no {path}; `make up` writes the first admin there")
    env = read_env(path)
    # An install's bootstrap file (deploy/images/first_admin.sh, make up) names its first admin under OPS_BOOTSTRAP_*.
    for name in ("EMAIL", "PASSWORD"):
        env.setdefault(f"OPS_DEMO_ADMIN_{name}", env.get(f"OPS_BOOTSTRAP_ADMIN_{name}", ""))
    if not env.get("OPS_DEMO_PASSWORD"):
        env["OPS_DEMO_PASSWORD"] = f"nf-{uuid.uuid4().hex[:20]}"
        with path.open("a") as out:
            out.write(f"OPS_DEMO_PASSWORD={env['OPS_DEMO_PASSWORD']}\n")
        path.chmod(0o600)
        say("MADE", "sample people's password", f"kept in {path}")
    missing = [k for k in ("OPS_DEMO_ADMIN_EMAIL", "OPS_DEMO_ADMIN_PASSWORD") if not env.get(k)]
    if missing:
        raise SystemExit(f"sample-team: {path} has no {', '.join(missing)}")
    return env


def install(args: argparse.Namespace) -> int:
    env = admin_env(args.admin_env)
    if args.expect_found:
        EXPECT_FOUND.append(True)
    spec = json.loads(MANIFEST.read_text())
    check_manifest(spec)
    if args.name:
        spec["team"]["name"] = args.name
        named(spec, args.name)
    if args.workflow_prefix or args.name:
        prefixed(spec, args.workflow_prefix or prefix_of(args.name))
    members = [tuple(m.rsplit(":", 1)) for m in args.member]
    if members and not os.environ.get(args.member_password_env):
        raise SystemExit(f"sample-team: --member needs the members' password in {args.member_password_env}")
    urls = service_urls(args.origin)
    email, password = env["OPS_DEMO_ADMIN_EMAIL"], env["OPS_DEMO_ADMIN_PASSWORD"]
    admin = sign_in(urls, email, password)
    team = ensure_team(admin, spec["team"])
    # A token names the teams its person was in when it was issued; sign in again to act in the new team.
    admin = sign_in(urls, email, password, team)
    people = ensure_people(admin, team, spec["people"], env["OPS_DEMO_PASSWORD"])
    if members:
        ensure_members(admin, team, [(e, r) for e, r in members], os.environ[args.member_password_env])
    people["admin"] = admin
    ADMIN.append(admin)
    lead, builder, approver = people["lead"], people["builder"], people["approver"]
    ensure_templates(builder, spec["templates"])
    knowledge = ensure_knowledge(builder, spec["knowledge"])
    model = env.get("OPS_DEMO_MODEL_ALIAS") or spec["fakes"]["modelAlias"]
    MODELS.scripted, MODELS.live = model, env.get("OPS_DEMO_LIVE_MODEL_ALIAS") or None
    MODELS.builder, MODELS.approver = builder, approver
    ensure_fakes(admin, lead, spec["fakes"])
    ensure_bank_module(builder, admin)
    pins = {
        "skills": ensure_skills(builder, approver, spec["skills"]),
        "guardrails": ensure_guardrails(builder, approver, spec["guardrails"]),
    }
    agents = ensure_agents(builder, approver, spec["agents"], knowledge, model, pins=pins)
    MODELS.agents = agents
    ensure_default_agent(admin, agents, spec["team"].get("defaultAgent"))
    names = {f"agent:{k}": v for k, v in agents.items()} | ids_by_key(spec)
    if not args.no_levy:
        security = sign_in(urls, email, password, SECURITY_TEAM)
        ensure_code_modules(builder, security, spec["codeModules"])
    ensure_document_types(builder, spec["documentTypes"])
    mailbox = ensure_mailbox(admin, lead, env, spec["mailbox"])
    ensure_workflows(builder, approver, team_workflows(spec, no_levy=args.no_levy), names, mailbox)
    if args.tool_access:
        if not (args.tool_access_team and args.tool_approver and os.environ.get(args.tool_approver_password_env)):
            raise SystemExit("sample-team: --tool-access needs --tool-access-team, --tool-approver and its password")
        tool_approver = sign_in(urls, args.tool_approver, os.environ[args.tool_approver_password_env])
        why = "The team's workflows read customers and accounts and write holds and replies through these tools."
        ensure_tool_access(
            admin, team, owning_team=args.tool_access_team, modules=args.tool_access, approver=tool_approver, why=why
        )
    MODELS.live_now()
    print(f"\n{len(FAILED)} failed", flush=True)
    return len(FAILED)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("install", help="install the sample team; a second run finds it and makes nothing")
    console = f"http://localhost:{os.environ.get('OPS_CONSOLE_PORT', '3016')}"
    run_dir = Path(os.environ.get("OPS_RUN_DIR") or ROOT / ".run")
    cmd.add_argument("--origin", default=console, help=f"the install's public address (default {console})")
    cmd.add_argument(
        "--admin-env",
        type=Path,
        default=run_dir / "dev-admin.env",
        help="file with OPS_BOOTSTRAP_ADMIN_* (or OPS_DEMO_ADMIN_*) and the people's OPS_DEMO_* settings",
    )
    cmd.add_argument("--expect-found", action="store_true", help="fail on any record this run makes (a second run)")
    cmd.add_argument("--name", help="install another team under this name, its workflow and document type ids prefixed")
    cmd.add_argument(
        "--member",
        action="append",
        default=[],
        metavar="EMAIL:ROLE",
        help="a person outside the manifest who joins the team with ROLE; repeatable. Their password is in the "
        "environment variable --member-password-env names",
    )
    cmd.add_argument("--member-password-env", default="OPS_DEMO_MEMBER_PASSWORD")
    cmd.add_argument(
        "--workflow-prefix", default="", help="the prefix for workflow and document type ids (--name's own)"
    )
    cmd.add_argument(
        "--tool-access",
        action="append",
        default=[],
        metavar="MODULE_ID",
        help="a tool module another team owns that the team's workflows are granted; repeatable",
    )
    cmd.add_argument("--tool-access-team", help="the team that owns the --tool-access modules and decides the grants")
    cmd.add_argument("--tool-approver", help="a person who decides that team's tool access requests")
    cmd.add_argument("--tool-approver-password-env", default="OPS_DEMO_TOOL_APPROVER_PASSWORD")
    cmd.add_argument(
        "--no-levy",
        action="store_true",
        help="leave out the levy story's workflows and code module: their read runs on the documents model, a real one "
        "on staging, where deploy/fly/staging/mailbox_demo.py makes them instead",
    )
    return install(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
