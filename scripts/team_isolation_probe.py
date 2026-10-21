"""A person outside a team reads none of its records (c-407): every GET route in every service's committed OpenAPI is
called as a member of team A with team B's ids, and any 200 that carries one of B's ids is a leak.

    OUTSIDER_PASSWORD=... OWNER_PASSWORD=... uv run python scripts/team_isolation_probe.py \
      --origin https://<install> --outsider <email> --team-a <id> --owner <email> --team-b <id>

    uv run python scripts/team_isolation_probe.py --origin http://localhost:4016 --make-outsider \
      --owner m.okafor@northfieldbank.com --team-b team_ops --seed

The owner (a member of B) lists every collection route acting in B, and each row's `id` becomes one of B's ids under
that route's path. The outsider then calls each collection route acting in A, and each item route with B's ids in its
first path parameter (a parameter named like a version gets 1). An item route counts only where the owner's own call
with the same id answered 200, so a route that answers 404 to everyone proves nothing and says VACUOUS.

`--seed` makes one record of each kind in B through the public API first (an agent, a knowledge base, a case, a skill,
a guardrail, a widget, a blank tool module, a file), so a kind B lacks is still probed. `--make-outsider` makes team A
("Isolation probe") and a person who belongs to it only, by invitation, signed in with OUTSIDER_PASSWORD.

Passwords come from environment variables only and are never printed. Every line says LEAK, OK, SKIP or VACUOUS; the
exit status is the number of LEAK lines.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "demo"))
from seed_demo_team import Session, data, items, service_urls, sign_in  # noqa: E402

# The services whose committed OpenAPI is probed, by the path prefix the origin serves them under.
SERVICES = ("agents", "tools", "kb", "files", "documents", "platform")
# Routes that read no team's records: identity, health, schemas and catalogues every member reads.
# Event streams hold the connection open, so they are read through the run or thread routes beside them.
NOT_TEAM_DATA = re.compile(r"/health$|^/\.well-known|^/v1/auth/|^/v1/me(/|$)|/node-types$|/openapi|/events$|/stream$")
TIMEOUT_S = 20.0
VERSION_PARAM = re.compile(r"version", re.I)


# GET routes a service serves outside its committed OpenAPI (the chat API is left out of agents-service's document).
EXTRA_GETS: dict[str, list[str]] = {
    "agents": ["/chat/agents", "/chat/default-agent", "/chat/threads", "/chat/threads/{thread_id}"],
}


def routes(service: str) -> list[tuple[str, list[str], list[str]]]:
    """Each GET path of `service` (its committed OpenAPI and EXTRA_GETS), its path parameters and its required query
    parameters."""
    spec = json.loads((ROOT / "services" / f"{service}-service" / "openapi.json").read_text())
    out = []
    for path, ops in sorted(spec["paths"].items()):
        get = ops.get("get")
        if get is None or NOT_TEAM_DATA.search(path):
            continue
        params = [*get.get("parameters", []), *ops.get("parameters", [])]
        required = [p["name"] for p in params if p.get("in") == "query" and p.get("required")]
        out.append((path, re.findall(r"{([^}]+)}", path), required))
    out += [(path, re.findall(r"{([^}]+)}", path), []) for path in EXTRA_GETS.get(service, [])]
    return out


def get(who: Session, service: str, path: str, **params: Any) -> httpx.Response | None:
    """One GET, or None when it did not answer within TIMEOUT_S."""
    try:
        return who(service).get(path, params=params or None, timeout=TIMEOUT_S)
    except httpx.TimeoutException:
        return None


TEAM_KEYS = ("teamId", "team_id", "team")
# The key a record's id is under: `id` for most, `widgetId` for a widget template.
ID_KEYS = ("id", "widgetId")


def id_of(row: Any) -> str | None:
    if not isinstance(row, dict):
        return None
    return next((str(row[k]) for k in ID_KEYS if isinstance(row.get(k), str) and row[k]), None)


def ids_in(body: Any) -> set[str]:
    """Every `id` value in a JSON body, at any depth."""
    found: set[str] = set()
    if isinstance(body, dict):
        for k, v in body.items():
            if k in ID_KEYS and isinstance(v, str):
                found.add(v)
            found |= ids_in(v)
    elif isinstance(body, list):
        for v in body:
            found |= ids_in(v)
    return found


def team_of(row: Any) -> str | None:
    """The team a row or record names as its owner, if its wire shape carries one."""
    if not isinstance(row, dict):
        return None
    return next((str(row[k]) for k in TEAM_KEYS if isinstance(row.get(k), str) and row[k]), None)


@dataclass
class Owned:
    """What the owner reads in B: every row's id by collection path, and which ids are known to be B's."""

    by_path: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    mine: set[str] = field(default_factory=set)
    untagged: set[str] = field(default_factory=set)


def collect(owner: Session, team_b: str, seeded: set[str]) -> Owned:
    """B's rows by (service, collection path), read by the owner acting in B. An id is B's when its row names team B
    or the probe made it in B; a row whose wire shape names no team is untagged and probed only when seeded."""
    owned = Owned(mine=set(seeded))
    for service in SERVICES:
        for path, params, required in routes(service):
            if params or required:
                continue
            r = get(owner, service, path, pageSize=100)
            if r is None or r.status_code != 200:
                continue
            rows = [x for x in items(r.json().get("data") if r.content else None) if isinstance(x, dict)]
            ids = [i for i in (id_of(x) for x in rows) if i]
            for x in rows:
                row_id = id_of(x)
                if row_id is None:
                    continue
                team = team_of(x)
                if team == team_b:
                    owned.mine.add(row_id)
                elif team is None and row_id not in seeded:
                    owned.untagged.add(row_id)
            if ids:
                # B's own ids first, so an item route is probed with a record B owns when it has one.
                owned.by_path[(service, path)] = sorted(ids, key=lambda i: i not in owned.mine)[:8]
    return owned


def body_of(r: httpx.Response) -> Any:
    """The JSON body, or None for bytes (a file's content)."""
    try:
        return r.json() if r.content else None
    except ValueError:
        return None


def probe(owner: Session, outsider: Session, owned: Owned, team_b: str) -> int:
    """An untagged id (its wire shape names no team) that the outsider's own team also lists is a workspace-level
    record both read (a built-in role or case type) and is printed SHARED to be judged; one A does not list is B's,
    so the outsider reading it is a leak."""
    leaks = 0
    a_lists = {i for ids in collect(outsider, "", set()).by_path.values() for i in ids}

    def line(state: str, what: str, detail: str = "") -> None:
        nonlocal leaks
        leaks += state == "LEAK"
        print(f"{state:<9} {what}{f': {detail}' if detail else ''}", flush=True)

    for service in SERVICES:
        for path, params, required in routes(service):
            what = f"GET /api/{service}{path}"
            if required:
                line("SKIP", what, f"needs query {', '.join(required)}")
                continue
            if not params:
                r = get(outsider, service, path, pageSize=100)
                if r is None:
                    line("SKIP", what, f"no answer in {TIMEOUT_S:.0f} s")
                    continue
                seen = ids_in(body_of(r)) & owned.mine if r.status_code == 200 else set()
                line(
                    "LEAK" if seen else "OK",
                    what,
                    f"{r.status_code}, B's {sorted(seen)[:3]}" if seen else str(r.status_code),
                )
                continue
            first, rest = params[0], params[1:]
            if any(not VERSION_PARAM.search(p) for p in rest):
                line("SKIP", what, f"no value for {', '.join(rest)}")
                continue
            prefix = path.split("{" + first + "}")[0].rstrip("/")
            candidates = owned.by_path.get((service, prefix), [])
            if not candidates:
                line("SKIP", what, f"B has no rows under {prefix}")
                continue
            state, detail = "VACUOUS", "the owner's own read of B's ids did not answer 200"
            for b_id in candidates:
                url = path.replace("{" + first + "}", b_id)
                for p in rest:
                    url = url.replace("{" + p + "}", "1")
                mine = get(owner, service, url)
                if mine is None or mine.status_code != 200:
                    continue
                record = (body_of(mine) or {}).get("data")
                if b_id not in owned.mine and team_of(record) == team_b:
                    owned.mine.add(b_id)
                if b_id not in owned.mine and b_id in a_lists:
                    state, detail = "SHARED", f"{b_id}: listed to both teams and names no team"
                    continue
                r = get(outsider, service, url)
                if r is None:
                    state, detail = "SKIP", f"{b_id}: no answer in {TIMEOUT_S:.0f} s"
                elif r.status_code == 200 and b_id in r.text:
                    state, detail = "LEAK", f"{b_id} answered 200 with B's record"
                else:
                    state, detail = "OK", f"{b_id} answered {r.status_code}"
                break
            line(state, what, detail)
    return leaks


# ── Setup: team A's outsider and one record of each kind in B ──────────────────────────────────────────────────


def make_outsider(owner: Session, password: str) -> tuple[str, str]:
    """Team "Isolation probe" and a person who belongs to it only; returns (email, team id)."""
    teams = items(data(owner("platform").get("/v1/settings/teams", params={"search": "Isolation probe"})))
    team = next((t for t in teams if t["name"] == "Isolation probe"), None)
    if team is None:
        team = data(
            owner("platform").post("/v1/settings/teams", json={"name": "Isolation probe", "admin": owner.email})
        )
    team_id = str(team["id"])
    there = sign_in(owner.urls, owner.email, owner.password, team_id)
    email = f"outsider-{uuid.uuid4().hex[:8]}@isolation-probe.example"
    invited = data(there("platform").post("/v1/settings/members/invite", json={"emails": [email], "role": "admin"}))
    token = invited["invites"][0]["token"]
    data(
        httpx.post(f"{owner.urls['platform']}/v1/invites/{token}/accept", json={"name": "Probe", "password": password})
    )
    print(f"MADE      outsider {email} in {team_id}", flush=True)
    return email, team_id


# What removes a seeded record, by kind: a DELETE path, or a POST that retires it where no delete route exists. A case
# has neither, so it stays, named in the output.
REMOVE: dict[str, tuple[str, str, str]] = {
    "agent": ("agents", "DELETE", "/v1/agents/{id}"),
    "skill": ("agents", "DELETE", "/v1/skills/{id}"),
    "guardrail": ("agents", "DELETE", "/v1/guardrails/{id}"),
    "widget": ("agents", "POST", "/v1/widgets/{id}/retire"),
    "knowledge base": ("kb", "DELETE", "/v1/knowledge-bases/{id}"),
    "tool module": ("tools", "DELETE", "/v1/tool-modules/{id}"),
    "file": ("files", "DELETE", "/v1/files/{id}"),
}


def remove(owner: Session, made: list[tuple[str, str]]) -> None:
    """Removes what `seed` made, so a probe run leaves the team as it found it where routes allow."""
    for kind, made_id in made:
        if kind not in REMOVE:
            print(f"KEPT      seed {kind} {made_id}: no route removes it", flush=True)
            continue
        service, method, path = REMOVE[kind]
        body = {"reason": "Isolation probe record"} if method == "POST" else None
        r = owner(service).request(method, path.replace("{id}", made_id), json=body)
        print(f"{'REMOVED' if r.status_code < 400 else 'KEPT':<9} seed {kind} {made_id}: {r.status_code}", flush=True)


def seed(owner: Session, made_ids: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """One record of each kind in B, each through the route the console uses; a refusal is printed and skipped.
    Appends (kind, id) to `made_ids` as each record is made, so a failure part way still removes the ones made."""
    tag = uuid.uuid4().hex[:6]
    body = f"isolation probe {tag}".encode()
    meta = {
        "name": f"probe-{tag}.txt",
        "size": len(body),
        "mime": "text/plain",
        "purpose": "case_attachment",
        "digest": hashlib.sha256(body).hexdigest(),
    }
    makes: list[tuple[str, str, str, dict[str, Any]]] = [
        ("agent", "agents", "/v1/agents", {"name": f"Probe agent {tag}", "role": "Isolation probe"}),
        ("case", "agents", "/v1/cases", {"subject": f"Probe case {tag}"}),
        (
            "skill",
            "agents",
            "/v1/skills",
            {"name": f"Probe skill {tag}", "useWhen": "Never.", "instructions": "None.", "ownerTeam": "Probe"},
        ),
        ("guardrail", "agents", "/v1/guardrails", {"name": f"Probe rule {tag}", "topics": ["probe"], "message": "No."}),
        (
            "widget",
            "agents",
            "/v1/widgets",
            {
                "name": f"Probe widget {tag}",
                "useWhen": "Never.",
                "tree": {"type": "card", "title": {"$bind": "/title"}, "children": []},
                "dataSchema": {"type": "object", "properties": {"title": {"type": "string"}}},
            },
        ),
        (
            "knowledge base",
            "kb",
            "/v1/knowledge-bases",
            {"name": f"Probe base {tag}", "description": "Isolation probe", "owner": owner.email},
        ),
        (
            "tool module",
            "tools",
            "/v1/tool-modules/blank",
            {"name": f"probe-{tag}", "displayName": f"Probe module {tag}", "type": "http"},
        ),
        ("file", "files", "/v1/files/uploads", meta),
    ]
    for kind, service, path, payload in makes:
        r = owner(service).post(path, json=payload, headers={"Idempotency-Key": f"probe-{tag}-{kind}"})
        if r.status_code >= 400:
            print(f"SKIP      seed {kind}: {r.status_code} {r.text[:160]}", flush=True)
            continue
        made = r.json().get("data") or {}
        made_id = str(made.get("id") or made.get("widgetId") or made.get("fileId") or "")
        if kind == "file" and made.get("uploadUrl"):
            owner("files").put(made["uploadUrl"], headers=made.get("headers") or {}, content=body)
            owner("files").post(f"/v1/files/uploads/{made_id}/complete")
        print(f"MADE      seed {kind} {made_id}", flush=True)
        if made_id:
            made_ids.append((kind, made_id))
    return made_ids


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origin", required=True)
    ap.add_argument("--owner", required=True, help="a member of team B; password in OWNER_PASSWORD")
    ap.add_argument("--team-b", required=True, help="the team whose records the outsider must not read")
    ap.add_argument("--outsider", help="a member of team A only; password in OUTSIDER_PASSWORD")
    ap.add_argument("--team-a", help="the team the outsider acts in")
    ap.add_argument("--make-outsider", action="store_true", help="make team A and its outsider with the owner")
    ap.add_argument("--seed", action="store_true", help="make one record of each kind in B first")
    args = ap.parse_args()
    urls = service_urls(args.origin)
    owner = sign_in(urls, args.owner, os.environ["OWNER_PASSWORD"], args.team_b)
    password = os.environ.get("OUTSIDER_PASSWORD") or f"probe-{uuid.uuid4().hex}"
    if args.make_outsider:
        email, team_a = make_outsider(owner, password)
        owner = sign_in(urls, args.owner, os.environ["OWNER_PASSWORD"], args.team_b)
    else:
        if not (args.outsider and args.team_a):
            raise SystemExit("probe: give --outsider and --team-a, or --make-outsider")
        email, team_a = args.outsider, args.team_a
    outsider = sign_in(urls, email, password, team_a)
    teams = [t["id"] for t in data(outsider("platform").get("/v1/me"))["teams"]]
    if args.team_b in teams:
        raise SystemExit(f"probe: {email} belongs to {args.team_b}, so it is no outsider")
    made: list[tuple[str, str]] = []
    try:
        made = seed(owner, made) if args.seed else []
        owned = collect(owner, args.team_b, {i for _, i in made})
        print(f"B's records: {len(owned.mine)} owned by B, {len(owned.untagged)} untagged", flush=True)
        leaks = probe(owner, outsider, owned, args.team_b)
    finally:
        remove(owner, made)
    print(f"\n{leaks} leaked", flush=True)
    return leaks


if __name__ == "__main__":
    sys.exit(main())
