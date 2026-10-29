"""Checks the logins a person demonstrates with against a demo team, through the public API only (c-405):

    MEMBER_PASSWORD=... VIEWER_PASSWORD=... uv run python scripts/check_demo_team.py --origin <install> \
      --team <demo team id> --admin <email> --builder <email> --approver <email> --viewer <email> \
      --test-team <test team id>

Each login signs in and acts in the demo team: the admin makes an agent and a workflow and edits both; the builder
edits the agent; the admin asks to publish the agent and the approver decides that request; the viewer is refused an
edit. A record made in the test team is then looked for from the demo team, by list and by id, and must be absent.
Everything the check makes is deleted at the end. Every line says PASS or FAIL; the exit status is the number of FAIL
lines. Passwords come from the environment and are never printed.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sample_team import Session, items, service_urls, sign_in

FAILED: list[str] = []


def check(ok: bool, what: str, detail: Any = "") -> None:
    if not ok:
        FAILED.append(what)
    print(f"{'PASS' if ok else 'FAIL'} {what}{'' if ok else f': {str(detail)[:300]}'}", flush=True)


def body(r: httpx.Response) -> Any:
    try:
        return r.json().get("data")
    except ValueError:
        return None


def workflow_yaml(wid: str, name: str) -> str:
    return f"""
schemaVersion: 2
id: {wid}
name: {name}
nodes:
  - {{id: start, type: ops.trigger.request, typeVersion: 1, name: Request}}
  - {{id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {{outcome: done}}}}
connections:
  - {{from: {{node: start, port: payload}}, to: {{node: done, port: in}}}}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origin", required=True)
    ap.add_argument("--team", required=True, help="the demo team's id")
    ap.add_argument("--test-team", required=True, help="a team the demo logins do not belong to")
    for role in ("admin", "builder", "approver", "viewer"):
        ap.add_argument(f"--{role}", required=True, help=f"the {role} login's email")
    ap.add_argument("--test-admin", help="an admin of the test team (default --admin); password in TEST_ADMIN_PASSWORD")
    args = ap.parse_args()
    urls = service_urls(args.origin)
    member_pw = os.environ["MEMBER_PASSWORD"]
    tag = uuid.uuid4().hex[:6]
    who: dict[str, Session] = {
        role: sign_in(urls, getattr(args, role), os.environ["VIEWER_PASSWORD"] if role == "viewer" else member_pw)
        for role in ("admin", "builder", "approver", "viewer")
    }
    for role, s in who.items():
        teams = {t["id"]: t["role"] for t in body(s("platform").get("/v1/me"))["teams"]}
        check(teams.get(args.team) == role, f"{role} login holds {role} in the demo team", teams)
        s.team = args.team
    made: list[tuple[Session, str, str, str]] = []
    admin, builder, approver, viewer = who["admin"], who["builder"], who["approver"], who["viewer"]
    try:
        r = admin("agents").post("/v1/agents", json={"name": f"Login check {tag}", "role": "Checks the demo logins"})
        check(r.status_code == 201, "admin creates an agent", r.text)
        agent = (body(r) or {}).get("id", "")
        if agent:
            made.append((admin, "agents", "DELETE", f"/v1/agents/{agent}"))
        r = admin("agents").patch(f"/v1/agents/{agent}", json={"role": "Checks the demo logins, edited by the admin"})
        check(r.status_code == 200, "admin edits the agent", r.text)
        r = builder("agents").patch(
            f"/v1/agents/{agent}", json={"role": "Checks the demo logins, edited by the builder"}
        )
        check(r.status_code == 200, "builder edits the agent", r.text)
        r = viewer("agents").patch(f"/v1/agents/{agent}", json={"role": "A viewer's edit"})
        check(r.status_code == 403, "viewer is refused an edit (403)", f"{r.status_code} {r.text}")
        wid = f"login_check_{tag}"
        r = admin("agents").post("/v1/workflows/definitions", json={"yaml": workflow_yaml(wid, f"Login check {tag}")})
        check(r.status_code in (200, 201), "admin creates a workflow", r.text)
        if r.status_code < 300:
            made.append((admin, "agents", "DELETE", f"/v1/workflows/definitions/{wid}"))
        r = admin("agents").post(
            "/v1/workflows/definitions", json={"yaml": workflow_yaml(wid, f"Login check {tag}, edited")}
        )
        check(r.status_code in (200, 201), "admin edits the workflow (saves a new draft)", r.text)
        asked = admin("agents").post(f"/v1/agents/{agent}/publish-requests", json={"version": 1, "note": "check"})
        request = body(asked) or {}
        check(asked.status_code < 300, "admin asks to publish the agent", asked.text)
        if request.get("status") == "pending":
            r = approver("agents").post(f"/v1/publish-requests/{request['id']}/decision", json={"decision": "approved"})
            check(r.status_code == 200, "approver decides the publish task", r.text)
        else:
            check(False, "approver decides the publish task", f"the request did not wait for review: {request}")
        # Isolation: a record of the test team is absent from the demo team, by list and by id.
        test_admin = sign_in(
            urls,
            args.test_admin or args.admin,
            os.environ.get("TEST_ADMIN_PASSWORD") or member_pw,
            args.test_team,
        )
        r = test_admin("agents").post("/v1/agents", json={"name": f"Test team record {tag}", "role": "Isolation check"})
        check(r.status_code == 201, "a record is made in the test team", r.text)
        theirs = (body(r) or {}).get("id", "")
        if theirs:
            made.append((test_admin, "agents", "DELETE", f"/v1/agents/{theirs}"))
        listed = [a["id"] for a in items(body(admin("agents").get("/v1/agents", params={"pageSize": 200})))]
        check(theirs not in listed, "the test team's agent is not listed in the demo team", listed)
        r = admin("agents").get(f"/v1/agents/{theirs}")
        check(r.status_code == 404, "the test team's agent answers 404 from the demo team", r.status_code)
    finally:
        for s, service, method, path in reversed(made):
            r = s(service).request(method, path)
            print(f"{'REMOVED' if r.status_code < 300 else 'KEPT   '} {path} {r.status_code}", flush=True)
    print(f"\n{len(FAILED)} failed", flush=True)
    return len(FAILED)


if __name__ == "__main__":
    sys.exit(main())
