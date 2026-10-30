"""uc-558 people connect their own Salesforce account, api layer: docs/usecases/tools-service/per-person-sign-in.md.
platform-service signs the seeded people in; tools-service and agents-service verify its tokens; the fake Salesforce
(navikt mock-oauth2-server in Docker behind an https front) records whose token each case edit carried. Runs go
through a worker, so whom each tool call acts for comes from the run's starter. No model call."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from collections.abc import Callable, Generator
from contextlib import ExitStack, contextmanager
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from fake_salesforce import WRITE_SCOPE, salesforce
from usecase_harness import (
    AGENTS_DIR,
    AGENTS_PORT,
    LOG_DIR,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    TOOLS_PORT,
    _env,  # pyright: ignore[reportPrivateUsage]
    agents,
    approve_tool_review,
    bearer,
    check,
    data,
    finish,
    pg_url,
    platform,
    service_headers,
    signed_in,
    tools,
)

from ops_service_kit import harness_containers

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
GW = f"http://127.0.0.1:{TOOLS_PORT}"
CONSOLE = "https://console.kestrel.test"
BASE_SCOPES = "openid api refresh_token"
DEFINITION = """
schemaVersion: 2
id: uc558_case_update
name: Case update (uc-558)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - id: update
    type: ops.action.tool
    typeVersion: 1
    name: Update the case
    parameters: {operation: uc558_update_case, input: {status: "$.input.status"}}
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
def worker() -> Generator[subprocess.Popen[bytes]]:
    """One worker on the run's database and gateway, verifying and asking platform-service as the services do."""
    env = _env() | AUTH
    env |= {"OPS_DATABASE_URL": pg_url(), "OPS_GATEWAY_URL": GW, "OPS_ENGINE_POLL_SECONDS": "0.2"}
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "worker-uc558.log").open("ab") as fh:
        proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "ops_agents.api.worker"], cwd=AGENTS_DIR, env=env, stdout=fh, stderr=fh
        )
    try:
        yield proc
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def until(what: Callable[[], Any], timeout: float = 60) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found := what():
            return found
        time.sleep(0.3)
    return None


def run(api: httpx.Client, who: dict[str, str], key: str, status: str = "Awaiting documents") -> dict[str, Any]:
    """Starts the workflow as `who` and returns the finished run with its update step."""
    res = api.post(
        "/v1/runs", json={"workflowId": "uc558_case_update", "input": {"status": status}, "runKey": key}, headers=who
    )
    check(f"run {key} is accepted (202)", res.status_code == 202, res.text[:300])
    run_id = str((data(res) or {}).get("runId", "wfrun_missing"))

    def finished() -> dict[str, Any] | None:
        r = data(api.get(f"/v1/runs/{run_id}", headers=who)) or {}
        return r if r.get("status") in ("succeeded", "failed") else None

    done = until(finished) or {}
    step = next((s for s in done.get("steps", []) if s.get("nodeId") == "update"), {})
    return {"outcome": done.get("outcome"), "step": step, "text": json.dumps(step)}


def link_of(step_text: str) -> str:
    """The connect link's token from a CONNECTION_NOT_LINKED answer."""
    for word in step_text.replace('"', " ").split():
        if "/connections/connect?" in word:
            return parse_qs(urlsplit(word).query).get("link", [""])[0]
    return ""


def connect(gw: httpx.Client, sf: dict[str, Any], who: dict[str, str], link: str, account: str) -> httpx.Response:
    """Opens a connect link as `who`, signs in to Salesforce as `account`, and finishes the sign-in."""
    opened = gw.post("/v1/connections/connect-links/sign-in", json={"link": link}, headers=who)
    if opened.status_code != 200:
        return opened
    back = sf["sign_in"](data(opened)["authorizeUrl"], account)
    return gw.post(
        f"/v1/connections/{data(opened)['connectionId']}/sign-in/complete",
        json={"state": back.get("state", ""), "code": back.get("code", "")},
        headers=who,
    )


def own_sign_in(gw: httpx.Client, sf: dict[str, Any], who: dict[str, str], connection_id: str, account: str) -> None:
    """`who` signs in their own account from the connection itself, asking only for the connection's scopes."""
    started = gw.post(f"/v1/connections/{connection_id}/sign-in", json={"environment": "production"}, headers=who)
    back = sf["sign_in"]((data(started) or {}).get("authorizeUrl", ""), account) if started.status_code == 200 else {}
    done = gw.post(
        f"/v1/connections/{connection_id}/sign-in/complete",
        json={"state": back.get("state", ""), "code": back.get("code", "")},
        headers=who,
    )
    check(f"{account} signs in from the connection (200)", done.status_code == 200, done.text[:200])


def editors(sf: dict[str, Any]) -> list[str]:
    return [e["by"] for e in sf["fake"].state()["edits"]]


with ExitStack() as stack:
    sf = stack.enter_context(salesforce())
    api, _ = stack.enter_context(platform())
    stack.enter_context(
        tools(
            {**sf["settings"], **AUTH, "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}", "OPS_CONSOLE_URL": CONSOLE}
        )
    )
    agents_api = stack.enter_context(agents(gateway_url=GW, env=AUTH))
    priya = bearer(signed_in(api, "p.shah@harborpine.example"), "team_ops")
    james = bearer(signed_in(api, "j.richardson@harborpine.example"), "team_ops")
    wanjiru = bearer(signed_in(api, "w.kamau@harborpine.example"), "team_ops")
    ravi = bearer(signed_in(api, "r.menon@harborpine.example"), "team_ops")
    nadia = bearer(signed_in(api, "n.petrov@harborpine.example"), "team_security")
    gw = stack.enter_context(httpx.Client(base_url=GW, headers=priya, timeout=30))

    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    allowed = [gw.post("/v1/egress/hosts", json={"value": h, "note": "uc-558"}, headers=sam) for h in sf["hosts"]]
    allowed.append(gw.post("/v1/egress/ranges", json={"value": sf["range"], "note": "uc-558"}, headers=sam))
    check(
        "Sam lists Salesforce's hosts and the fake's range",
        all(r.status_code in (200, 201, 409) for r in allowed),
        [r.text[:120] for r in allowed],
    )
    made = gw.post(
        "/v1/connections",
        json={"name": "Salesforce claims (uc-558)", "authKind": "oauth2_auth_code", "signIn": "person"},
    )
    check("the Salesforce connection is created (201)", made.status_code == 201, made.text[:300])
    conn = data(made) or {}
    app = {
        "settings": {
            "baseUrl": sf["api_base"],
            "authorizeUrl": sf["authorize_url"],
            "tokenUrl": sf["token_url"],
            "revokeUrl": sf["revoke_url"],
            "clientId": "ops-ai-kestrel",
            "scopes": BASE_SCOPES,
            "testPath": "/services/oauth2/userinfo",
        },
        "secretValues": {"clientSecret": "kestrel-connected-app-secret"},
    }
    put = gw.put(
        f"/v1/connections/{conn.get('id', 'conn_missing')}/environments/production",
        json={"revision": conn.get("revision"), **app},
    )
    check("its production OAuth app is set (200)", put.status_code == 200, put.text[:300])
    conn = data(put) or conn
    check("the connection signs in with each person's own account", conn.get("signIn") == "person", conn.get("signIn"))
    http = {
        "name": "uc558_update_case",
        "description": "Update a Salesforce case's status",
        "access": "write",
        "method": "PATCH",
        "url": sf["case_url"],
        "body": '{"Status": {{status}}}',
    }
    body = {
        "name": "uc558-update-case",
        "displayName": "Salesforce cases",
        "system": "Salesforce",
        "type": "http",
        "endpoint": "",
        "connectionId": conn.get("id"),
        "http": http,
    }
    created = data(gw.post("/v1/tool-modules", json=body)) or {}
    op = (created.get("operations") or [{}])[0]
    gw.patch(f"/v1/tool-modules/{created.get('id')}/operations/{op.get('id')}", json={"requiresApproval": False})
    gw.post(f"/v1/tool-modules/{created.get('id')}/reviews", json={"note": "uc-558"})
    published = approve_tool_review(gw, str(created.get("id")), nadia)
    check("the Salesforce case module is published", published.get("status") == "published", published)
    scoped = gw.patch(
        f"/v1/tool-modules/{published.get('id')}/operations/{op.get('id')}", json={"scopes": [WRITE_SCOPE]}
    )
    scoped_op = next((o for o in (data(scoped) or {}).get("operations") or [] if o.get("id") == op.get("id")), {})
    check(
        "the update operation needs cases.write",
        scoped.status_code == 200 and scoped_op.get("scopes") == [WRITE_SCOPE],
        scoped.text[:300],
    )
    defined = agents_api.post("/v1/workflows/definitions", json={"yaml": DEFINITION}, headers=priya)
    live = agents_api.post("/v1/workflows/definitions/uc558_case_update/publish-requests", json={}, headers=priya)
    check(
        "the workflow goes live",
        defined.status_code == 201 and (data(live) or {}).get("status") == "approved",
        live.text[:300],
    )

    stack.enter_context(worker())

    # 1. James has not connected: the call is refused with a link made for him; nothing reaches Salesforce.
    first = run(agents_api, james, "uc558-james-1")
    james_link = link_of(first["text"])
    check(
        "1 James's run is refused with CONNECTION_NOT_LINKED and a connect link, and nothing reaches Salesforce",
        "CONNECTION_NOT_LINKED" in first["text"] and bool(james_link) and editors(sf) == [],
        first,
    )

    # 2. Ravi cannot finish James's link.
    stolen = gw.post("/v1/connections/connect-links/sign-in", json={"link": james_link}, headers=ravi)
    check(
        "2 Ravi opening James's link is refused (connect_link_not_yours)",
        stolen.status_code == 404 and "connect_link_not_yours" in stolen.text,
        (stolen.status_code, stolen.text[:200]),
    )

    # 3. James connects his own account.
    joined = connect(gw, sf, james, james_link, "handler@kestrel.example")
    shown = data(gw.get(f"/v1/connections/{conn.get('id')}", headers=priya)) or {}
    people = shown.get("people") or []
    check(
        "3 James finishes his own sign-in, and the connection lists his sign-in, not a team one",
        joined.status_code == 200 and [p.get("account") for p in people] == ["handler@kestrel.example"],
        (joined.status_code, joined.text[:200], people),
    )

    # 4. The same run now updates the case with James's token.
    second = run(agents_api, james, "uc558-james-2")
    # The call log is keyed by the call's idempotency key, which the run's step attempt names.
    call_key = ((second.get("step") or {}).get("attempts") or [{}])[-1].get("key") or "none"
    calls = (data(gw.get("/v1/executions", params={"key": call_key}, headers=priya)) or {}).get("data") or []
    logged = calls[0] if calls else {}
    check(
        "4 James's run updates the case as handler@kestrel.example, logged as person, acting for James",
        second["outcome"] == "updated"
        and editors(sf) == ["handler@kestrel.example"]
        and logged.get("credential") == "person"
        and str(logged.get("actingFor", "")).endswith("j.richardson@harborpine.example"),
        (second, editors(sf), logged),
    )

    # 5. Wanjiru never gets James's token.
    wanjiru_first = run(agents_api, wanjiru, "uc558-wanjiru-1")
    wanjiru_link = link_of(wanjiru_first["text"])
    check(
        "5 Wanjiru's run asks Wanjiru to connect; James's token is not used for her",
        "CONNECTION_NOT_LINKED" in wanjiru_first["text"]
        and bool(wanjiru_link)
        and editors(sf) == ["handler@kestrel.example"],
        wanjiru_first,
    )

    # 6. Wanjiru connects and her run carries her own token.
    connect(gw, sf, wanjiru, wanjiru_link, "supervisor@kestrel.example")
    wanjiru_second = run(agents_api, wanjiru, "uc558-wanjiru-2", "Escalated")
    check(
        "6 Wanjiru's run records supervisor@kestrel.example as the editor",
        wanjiru_second["outcome"] == "updated" and editors(sf)[-1:] == ["supervisor@kestrel.example"],
        (wanjiru_second, editors(sf)),
    )

    # 7. A person named only in the body chooses no token.
    forged = httpx.post(
        f"{GW}/v1/calls",
        json={
            "tool": "uc558_update_case",
            "input": {"status": "Closed"},
            "key": "uc558-forged",
            "runContext": {
                "act": "workflow:uc558",
                "environment": "production",
                "actingFor": "j.richardson@harborpine.example",
            },
        },
        headers=service_headers("tools", team="team_ops"),
        timeout=30,
    )
    check(
        "7 a call naming James only in its body is refused, and no edit reaches Salesforce",
        forged.status_code != 200 or "CONNECTION_NOT_LINKED" in forged.text,
    )
    check(
        "7 no edit reached Salesforce from the forged call",
        len(editors(sf)) == 2,
        (forged.status_code, forged.text[:300], editors(sf)),
    )

    # 8. Test connection as Priya, with her own account.
    own_sign_in(gw, sf, priya, str(conn.get("id")), "admin@kestrel.example")
    tested = gw.post(f"/v1/connections/{conn.get('id')}/test", json={"environment": "production"}, headers=priya)
    health = (data(gw.get(f"/v1/connections/{conn.get('id')}", headers=priya)) or {}).get("health") or {}
    check(
        "8 Test connection reads userinfo and stores the result on the connection",
        tested.status_code == 200 and health.get("status") == "ok",
        (tested.status_code, tested.text[:300], health),
    )

    # 9. Nobody behind the call: refused while the backup is off.
    nobody = httpx.post(
        f"{GW}/v1/calls",
        json={
            "tool": "uc558_update_case",
            "input": {"status": "Closed"},
            "key": "uc558-nobody",
            "runContext": {"act": "schedule:uc558", "environment": "production"},
        },
        headers=service_headers("tools", team="team_ops"),
        timeout=30,
    )
    revision = (data(gw.get(f"/v1/connections/{conn.get('id')}", headers=priya)) or {}).get("revision")
    backup = gw.patch(
        f"/v1/connections/{conn.get('id')}",
        json={"revision": revision, "signIn": "person_or_team", "teamBackup": True},
        headers=priya,
    )
    team = gw.post(
        f"/v1/connections/{conn.get('id')}/sign-in",
        json={"environment": "production", "account": "team"},
        headers=priya,
    )
    back = (
        sf["sign_in"]((data(team) or {}).get("authorizeUrl", ""), "svc-claims@kestrel.example")
        if team.status_code == 200
        else {}
    )
    gw.post(
        f"/v1/connections/{conn.get('id')}/sign-in/complete",
        json={"state": back.get("state", ""), "code": back.get("code", "")},
        headers=priya,
    )
    behind = httpx.post(
        f"{GW}/v1/calls",
        json={
            "tool": "uc558_update_case",
            "input": {"status": "Closed"},
            "key": "uc558-nobody-2",
            "runContext": {"act": "schedule:uc558", "environment": "production"},
        },
        headers=service_headers("tools", team="team_ops"),
        timeout=30,
    )
    check(
        "9 a call with nobody behind it is refused while the backup is off, and uses the team account once it is on",
        "CONNECTION_NOT_LINKED" in nobody.text
        and backup.status_code == 200
        and behind.status_code == 200
        and editors(sf)[2:] == ["svc-claims@kestrel.example"],
        (nobody.text[:200], backup.text[:200], behind.text[:200], editors(sf)),
    )

    # 9b. An operation marked needsPerson never takes the team backup, even with it on.
    module_id = str(published.get("id"))
    marked = gw.patch(f"/v1/tool-modules/{module_id}/operations/{op.get('id')}", json={"needsPerson": True})
    asked = data(gw.post(f"/v1/tool-modules/{module_id}/versions", json={"note": "uc-558 needs a person"})) or {}
    if any(v.get("status") == "in_review" for v in asked.get("versions") or []):
        approve_tool_review(gw, module_id, nadia)
    person_only = httpx.post(
        f"{GW}/v1/calls",
        json={
            "tool": "uc558_update_case",
            "input": {"status": "Closed"},
            "key": "uc558-nobody-3",
            "runContext": {"act": "schedule:uc558", "environment": "production"},
        },
        headers=service_headers("tools", team="team_ops"),
        timeout=30,
    )
    check(
        "9b an operation that needs a person is refused with nobody behind it, though the team backup is on",
        marked.status_code == 200 and "needs_person" in person_only.text,
        (marked.text[:200], person_only.text[:300]),
    )

    # 10. Priya signed in from the connection itself (step 8), its scopes only; a write needing cases.write asks again.
    priya_first = run(agents_api, priya, "uc558-priya-1")
    check(
        "10 Priya's run without cases.write is asked to connect again (insufficient_scope)",
        "CONNECTION_NOT_LINKED" in priya_first["text"] and "insufficient_scope" in priya_first["text"],
        priya_first,
    )

    # 11. James's own connections, then Disconnect.
    mine = data(gw.get("/v1/me/connections", headers=james)) or []
    listed = [c for c in mine if c.get("connectionId") == conn.get("id")]
    gone = gw.delete(f"/v1/me/connections/{conn.get('id')}", params={"environment": "production"}, headers=james)
    again = run(agents_api, james, "uc558-james-3")
    check(
        "11 James sees his Salesforce sign-in, disconnects it, and his next run asks him to connect again",
        bool(listed)
        and listed[0].get("account") == "handler@kestrel.example"
        and gone.status_code == 204
        and "CONNECTION_NOT_LINKED" in again["text"],
        (listed, gone.status_code, again),
    )

# The fake's OAuth server and the run's OPA are removed once the run's services stop.
left = harness_containers.owned_by(os.getpid())
check("12 the run leaves no container of its own behind", left == [], left)
finish()
