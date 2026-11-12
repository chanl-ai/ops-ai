"""The stack a use case page runs against (packages/usecase-runner/src/page.ts). Starts the services the page's Details
row names on the run's ports and database, writes a saved sign-in file with one profile per person on the page, prints
READY, and stops everything when the runner closes stdin. The page's code reads that file through OPS_CONFIG, as it
would read a developer's own profile."""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import tempfile
import threading
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
from usecase_harness import ROOT, fake_openai, kb, models

RERANK_RULES = ROOT / "services/kb-service/tests/fixtures/rerank-and-rewrite-fake-openai"


PEOPLE = {
    "priya": "p.shah@harborpine.example",
    "james": "j.richardson@harborpine.example",
    "wanjiru": "w.kamau@harborpine.example",
}
WORKFLOW = """
schemaVersion: 2
id: case_update
name: Case update
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - id: update
    type: ops.action.tool
    typeVersion: 1
    name: Update the case
    parameters: {operation: update_case, input: {status: "$.input.status"}}
  - {id: updated, type: ops.flow.end, typeVersion: 1, name: Updated, parameters: {outcome: updated}}
  - {id: refused, type: ops.flow.end, typeVersion: 1, name: Refused, parameters: {outcome: refused}}
  - {id: failed, type: ops.flow.end, typeVersion: 1, name: Failed, parameters: {outcome: failed}}
connections:
  - {from: {node: start, port: payload}, to: {node: update, port: in}}
  - {from: {node: update, port: ok}, to: {node: updated, port: in}}
  - {from: {node: update, port: refused}, to: {node: refused, port: in}}
  - {from: {node: update, port: error}, to: {node: failed, port: in}}
"""


@contextmanager
def _worker(auth: dict[str, str], gateway: str) -> Generator[None]:
    """One worker on the run's database and gateway, so a run goes on after a person connects."""
    from usecase_harness import AGENTS_DIR, LOG_DIR, _env, pg_url  # pyright: ignore[reportPrivateUsage]

    env = _env() | auth | {"OPS_DATABASE_URL": pg_url(), "OPS_GATEWAY_URL": gateway, "OPS_ENGINE_POLL_SECONDS": "0.2"}
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "worker-page.log").open("ab") as fh:
        proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "ops_agents.api.worker"], cwd=AGENTS_DIR, env=env, stdout=fh, stderr=fh
        )
    try:
        yield
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


@contextmanager
def _browser(sf: dict[str, Any]) -> Generator[str]:
    """A stand-in for the person's browser, so a page can finish a sign-in without one. POST /sign-in {url, as} opens the
    sign-in address at the fake Salesforce as that account and answers with the state and code the browser would come
    back with; GET /editors lists who the fake Salesforce has recorded as having edited the case."""

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: Any) -> None:
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            self._send([e["by"] for e in sf["fake"].state()["edits"]])

        def do_POST(self) -> None:
            asked = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            self._send(sf["sign_in"](asked.get("url", ""), asked.get("as", "")))

        def log_message(self, *_: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def _tools_stack(stack: ExitStack, names: list[str]) -> dict[str, dict[str, Any]]:
    """The tools stack: platform-service signing the page's people in, tools-service and agents-service verifying its
    tokens, a worker, and a fake Salesforce. The team has listed Salesforce's hosts, added the app so each person signs
    in as themselves, published its update tool and a workflow that calls it. Nobody has connected yet. One profile per
    person, each with that person's own tokens."""
    from fake_salesforce import WRITE_SCOPE, salesforce
    from usecase_harness import (
        AGENTS_PORT,
        PLATFORM_INTERNAL_PORT,
        PLATFORM_PORT,
        TOOLS_PORT,
        agents,
        approve_tool_review,
        bearer,
        data,
        platform,
        signed_in,
        tools,
    )

    auth = {
        "OPS_AUTH_MODE": "platform",
        "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
        "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
    }
    gateway = f"http://127.0.0.1:{TOOLS_PORT}"
    sf = stack.enter_context(salesforce())
    api, _inner = stack.enter_context(platform())
    stack.enter_context(
        tools(
            {
                **sf["settings"],
                **auth,
                "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}",
                "OPS_CONSOLE_URL": "https://console.kestrel.test",
            }
        )
    )
    agents_api = stack.enter_context(agents(gateway_url=gateway, env=auth))
    sessions = {n: signed_in(api, PEOPLE[n]) for n in names if n in PEOPLE}
    priya = bearer(sessions.get("priya") or signed_in(api, PEOPLE["priya"]), "team_ops")
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    nadia = bearer(signed_in(api, "n.petrov@harborpine.example"), "team_security")
    gw = stack.enter_context(httpx.Client(base_url=gateway, headers=priya, timeout=30))

    def need(label: str, res: httpx.Response, ok: tuple[int, ...] = (200, 201)) -> dict[str, Any]:
        if res.status_code not in ok:
            raise SystemExit(f"the stack could not {label}: {res.status_code} {res.text[:300]}")
        return data(res) or {}

    for host in sf["hosts"]:
        need(
            "list a host",
            gw.post("/v1/egress/hosts", json={"value": host, "note": "page"}, headers=sam),
            (200, 201, 409),
        )
    need(
        "list the range",
        gw.post("/v1/egress/ranges", json={"value": sf["range"], "note": "page"}, headers=sam),
        (200, 201, 409),
    )
    conn = need(
        "add the app",
        gw.post("/v1/apps", json={"name": "Salesforce claims", "authKind": "oauth2_auth_code", "signIn": "person"}),
    )
    settings = {
        "baseUrl": sf["api_base"],
        "authorizeUrl": sf["authorize_url"],
        "tokenUrl": sf["token_url"],
        "revokeUrl": sf["revoke_url"],
        "clientId": "ops-ai-kestrel",
        "scopes": f"openid api refresh_token {WRITE_SCOPE}",
        "testPath": "/services/oauth2/userinfo",
    }
    conn = need(
        "set its OAuth app",
        gw.patch(
            f"/v1/apps/{conn['id']}/accounts/{conn['id']}",
            json={
                "revision": conn.get("revision"),
                "settings": settings,
                "secretValues": {"clientSecret": "kestrel-connected-app-secret"},
            },
        ),
    )
    module = need(
        "make the module",
        gw.post(
            "/v1/tool-modules",
            json={
                "name": "salesforce-cases",
                "displayName": "Salesforce cases",
                "system": "Salesforce",
                "type": "http",
                "endpoint": "",
                "connectionId": conn["id"],
                "http": {
                    "name": "update_case",
                    "description": "Update a Salesforce case's status",
                    "access": "write",
                    "method": "PATCH",
                    "url": sf["case_url"],
                    "body": '{"Status": {{status}}}',
                },
            },
        ),
    )
    op = (module.get("operations") or [{}])[0]
    gw.patch(f"/v1/tool-modules/{module['id']}/operations/{op.get('id')}", json={"requiresApproval": False})
    gw.post(f"/v1/tool-modules/{module['id']}/reviews", json={"note": "page"})
    published = approve_tool_review(gw, str(module["id"]), nadia)
    need(
        "scope the operation",
        gw.patch(f"/v1/tool-modules/{published.get('id')}/operations/{op.get('id')}", json={"scopes": [WRITE_SCOPE]}),
    )
    need(
        "define the workflow",
        agents_api.post("/v1/workflows/definitions", json={"yaml": WORKFLOW}, headers=priya),
        (201,),
    )
    live = need(
        "publish the workflow",
        agents_api.post("/v1/workflows/definitions/case_update/publish-requests", json={}, headers=priya),
        (200, 201),
    )
    if live.get("status") != "approved":
        raise SystemExit(f"the workflow did not go live: {live}")
    stack.enter_context(_worker(auth, gateway))
    services = {
        "tools": gateway,
        "agents": f"http://127.0.0.1:{AGENTS_PORT}",
        "platform": f"http://127.0.0.1:{PLATFORM_PORT}",
        "browser": stack.enter_context(_browser(sf)),
    }
    return {
        n: {
            "baseUrl": f"http://127.0.0.1:{PLATFORM_PORT}",
            "team": "team_ops",
            "services": services,
            "accessToken": s.get("token"),
            "refreshToken": s.get("refreshToken"),
        }
        for n, s in sessions.items()
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--profiles", required=True)
    ap.add_argument("--services", default="")
    ns = ap.parse_args()
    services: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="usecase-page-") as tmp, ExitStack() as stack:
        # Pages say which services in words; knowledge brings its files and documents services with it.
        if "SharePoint" in ns.services:
            # A team that has signed SharePoint and Confluence in, as its admin does in Apps; the page starts from there.
            from fake_sharepoint_confluence import connect
            from fake_sharepoint_confluence import stack as document_stack

            k, gw, systems = stack.enter_context(document_stack(Path(tmp)))
            done = connect(
                gw, systems, {"X-Team-Id": "team_ops"}, {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}
            )
            if done["sharepoint"]["done"] != 200 or (done["confluence"]["health"] or {}).get("status") != "ok":
                raise SystemExit(f"the apps did not connect: {done}")
            services["kb"] = str(k.base_url).rstrip("/")
        elif "knowledge" in ns.services:
            env = None
            if "scripted chat model" in ns.services:
                # Rerank and rewrite call a chat model; the fake answers their prompts from the fixture, so no provider is called.
                fake = stack.enter_context(fake_openai(RERANK_RULES))
                models_url = stack.enter_context(models({"OPS_MODELS_FAKE_OPENAI_URL": fake}))
                env = {"OPS_MODELS_URL": models_url, "OPS_MODELS_KEY": "mk_dev_kb"}
            store = stack.enter_context(kb(Path(tmp) / "files", env=env))
            services["kb"] = str(store.base_url).rstrip("/")
            services["files"] = store.files_url.rstrip("/")
        if "starters pack" in ns.services:
            from agents_stack import agents_stack

            profiles = agents_stack(stack, ns.profiles.split(","), "MCP" in ns.services)
            Path(ns.config).write_text(json.dumps({"profiles": profiles, "current": next(iter(profiles))}))
            print("READY", flush=True)
            sys.stdin.read()
            return
        if "Salesforce" in ns.services:
            profiles = _tools_stack(stack, ns.profiles.split(","))
            Path(ns.config).write_text(json.dumps({"profiles": profiles, "current": next(iter(profiles))}))
            print("READY", flush=True)
            sys.stdin.read()
            return
        if not services:
            raise SystemExit(f"page_stack starts the knowledge services only; the page asks for: {ns.services!r}")
        profile = {"baseUrl": "http://127.0.0.1", "team": "team_ops", "services": services}
        names = ns.profiles.split(",")
        Path(ns.config).write_text(json.dumps({"profiles": dict.fromkeys(names, profile), "current": names[0]}))
        print("READY", flush=True)
        sys.stdin.read()


main()
