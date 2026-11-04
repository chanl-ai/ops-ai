"""uc-617, api layer: docs/usecases/tools-service/an-app-that-fails-says-why.md, stories S1-S3 (steps 1-4c).
The Apps stack (docs/usecases/lib/apps_walk.py). Every step waits on work not built yet and names
it. No model call."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from apps_walk import AUTH, account_path, app_path, apps_stack, target
from usecase_harness import TOOLS_PORT, agents, check, data, engine_worker, finish, until

APP = "plugin:test.client"

with (
    # A sign-in returns to the console's address (step 3d signs the team account in).
    apps_stack(tools_env={"OPS_CONSOLE_URL": "https://console.harborpine.test"}) as w,
    agents(gateway_url=str(w.gw.base_url).rstrip("/"), env=AUTH) as api,
    engine_worker("uc-617", AUTH | {"OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}"}),
):
    # 1. A team account the app refuses shows Refused.
    wrong = w.credential("admin", "test.client", "multi-cc", "wrong-secret-0000")
    account = w.turn_on("admin", "test.client", credentialId=wrong)
    failed = w.call("client_get_record", args={"id": "rec-1042"})
    page = data(w.kept(w.gw.get(app_path(APP), headers=w.who["admin"]))) or {}
    team = next((a for a in page.get("accounts") or [] if a.get("id") == account), {})
    check(
        "1 the client desk's team account reads refused, with the sign-in server's reason",
        team.get("state") == "refused" and "invalid_client" in str(team.get("stateReason")),
        (target("D2 and S12"), team),
    )

    # 2. The run's refusal says the app needs reconnecting.
    error = ((data(failed) or {}).get("output") or {}).get("error") or {}
    check(
        "2 the run's call says Client desk needs reconnecting, with no secret in it",
        "needs reconnecting" in str(error.get("message"))
        and "Client desk" in str(error.get("message"))
        and "wrong-secret-0000" not in failed.text,
        (target("S12"), error),
    )

    # 3. A run James started pauses for his own account, and goes on by itself once he gives his key.
    w.turn_on("admin", "test.person-key", signIn="person")
    flow = f"uc617_{uuid4().hex[:6]}"

    def node(nid: str, kind: str, **params: Any) -> dict[str, Any]:
        return {"id": nid, "type": kind, "typeVersion": 1, "name": nid.capitalize(), "parameters": params}

    definition = {
        "schemaVersion": 2,
        "id": flow,
        "name": "Read a desk record",
        "nodes": [
            node("start", "ops.trigger.request"),
            node("read", "ops.action.tool", operation="person_key_get_record", input={"id": "rec-1042"}),
            node("done", "ops.flow.end", outcome="read", output="$.nodes.read.out"),
            node("failed", "ops.flow.end", outcome="not_read", result="failed"),
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "read", "port": "in"}},
            {"from": {"node": "read", "port": "ok"}, "to": {"node": "done", "port": "in"}},
            {"from": {"node": "read", "port": "error"}, "to": {"node": "failed", "port": "in"}},
            {"from": {"node": "read", "port": "refused"}, "to": {"node": "failed", "port": "in"}},
        ],
    }
    # Priya saves and publishes it (she holds the reviewer role); James starts it, so its calls act for him.
    api.post("/v1/workflows/definitions", json={"definition": definition}, headers=w.who["admin"])
    live = api.post(f"/v1/workflows/definitions/{flow}/publish-requests", json={}, headers=w.who["admin"])
    started = api.post("/v1/runs", json={"workflowId": flow, "input": {}}, headers=w.who["builder"])
    run_id = str((data(started) or {}).get("id") or (data(started) or {}).get("runId") or "")

    def run() -> dict[str, Any]:
        return data(api.get(f"/v1/runs/{run_id}", headers=w.who["builder"])) or {}

    paused = until(lambda: (r := run()).get("status") in ("waiting", "succeeded", "failed") and r, timeout=60) or {}
    wait = (paused.get("waiting") or {}).get("payload") or {}
    check(
        "3 a run James started waits for his own Person key desk account instead of failing",
        paused.get("status") == "waiting"
        and wait.get("event") == "app_account.connected"
        and wait.get("title") == "Connect your Person key desk account to continue",
        (live.status_code, started.text[:200], paused.get("status"), paused.get("error"), wait),
    )
    # 3b. Human Tasks lists the wait for James as a connect_account task naming the app.
    listed = data(api.get("/reviews", params={"pageSize": 100}, headers=w.who["builder"])) or {}
    rows = listed.get("data") if isinstance(listed, dict) else listed
    task = next((r for r in rows or [] if r.get("runId") == run_id), {})
    connect = task.get("connect") or {}
    check(
        "3b Human Tasks lists James's wait as a connect_account task for the Person key desk, with no deadline",
        task.get("kind") == "connect_account"
        and connect.get("app") == "Person key desk"
        and connect.get("person") == "j.richardson@harborpine.example"
        and connect.get("teamAccount") is False
        and task.get("dueAt") is None,
        {k: task.get(k) for k in ("id", "kind", "title", "connect", "dueAt")},
    )
    # 3c. Run as the team account: refused to James by his role, and to Priya because the desk has no team account.
    as_team = f"/reviews/{task.get('id') or run_id}/team-account"
    by_james = api.post(as_team, headers=w.who["builder"])
    by_priya = api.post(as_team, headers=w.who["admin"])
    decided = api.post(
        f"/reviews/{task.get('id') or run_id}/decision", json={"decision": "approve"}, headers=w.who["admin"]
    )
    check(
        "3c Run as the team account is refused to James (connections.run) and on a desk with no team account",
        by_james.status_code == 403
        and by_priya.status_code == 409
        and "no team account" in by_priya.text
        and decided.status_code == 409
        and "connect_wait" in decided.text,
        (by_james.status_code, by_james.text[:160], by_priya.text[:200], decided.text[:200]),
    )
    desk = data(w.kept(w.gw.get(app_path("plugin:test.person-key"), headers=w.who["admin"]))) or {}
    given = w.kept(
        w.gw.put(
            f"/v1/me/accounts/{(desk.get('card') or {}).get('connectionId')}/credentials",
            json={"credentials": {"key": w.m["person_keys"]["james"]}},
            headers=w.who["builder"],
        )
    )
    went_on = until(lambda: (r := run()).get("status") in ("succeeded", "failed") and r, timeout=60) or {}
    check(
        "3a once James gives his key the run goes on by itself and reads the record",
        given.status_code == 200 and went_on.get("status") == "succeeded" and went_on.get("outcome") == "read",
        (given.status_code, given.text[:200], went_on.get("status"), went_on.get("error")),
    )

    # 3d. On a desk whose team account backs its people, Priya (connections.run) runs her own waiting run as the team
    # account, and it reads the record with the team's token.
    own = w.credential("admin", "test.person", "multi-app", w.m["clients"]["multi-app"])
    backed = w.turn_on("admin", "test.person", signIn="person_or_team", credentialId=own)
    backed_path = account_path("plugin:test.person", backed)
    revision = (data(w.gw.get(backed_path, headers=w.who["admin"])) or {}).get("revision")
    w.gw.patch(
        backed_path,
        json={"revision": revision, "signIn": "person_or_team", "teamBackup": True},
        headers=w.who["admin"],
    )
    team = w.gw.post(
        f"{backed_path}/sign-in",
        json={"account": "team"},
        headers=w.who["admin"],
    )
    back = (
        w.m["sign_in"]((data(team) or {}).get("authorizeUrl", ""), "desk-team@harborpine.example")
        if team.status_code == 200
        else {}
    )
    signed = w.gw.post(
        f"{backed_path}/sign-in/complete",
        json={"state": back.get("state", ""), "code": back.get("code", "")},
        headers=w.who["admin"],
    )
    team_flow = {
        **definition,
        "id": f"{flow}_team",
        "nodes": [
            n | {"parameters": {**n["parameters"], "operation": "person_get_record"}} if n["id"] == "read" else n
            for n in definition["nodes"]
        ],
    }
    api.post("/v1/workflows/definitions", json={"definition": team_flow}, headers=w.who["admin"])
    api.post(f"/v1/workflows/definitions/{team_flow['id']}/publish-requests", json={}, headers=w.who["admin"])
    begun = api.post("/v1/runs", json={"workflowId": team_flow["id"], "input": {}}, headers=w.who["admin"])
    team_run = str((data(begun) or {}).get("id") or (data(begun) or {}).get("runId") or "")

    def run_of(rid: str) -> dict[str, Any]:
        return data(api.get(f"/v1/runs/{rid}", headers=w.who["admin"])) or {}

    waited = (
        until(lambda: (r := run_of(team_run)).get("status") in ("waiting", "succeeded", "failed") and r, timeout=60)
        or {}
    )
    as_team_ok = api.post(f"/reviews/{team_run}/team-account", headers=w.who["admin"])
    finished = until(lambda: (r := run_of(team_run)).get("status") in ("succeeded", "failed") and r, timeout=60) or {}
    check(
        "3d Priya runs her waiting run as the desk's team account and it reads the record with the team's token",
        signed.status_code == 200
        and waited.get("status") == "waiting"
        and as_team_ok.status_code == 200
        and finished.get("status") == "succeeded"
        and finished.get("outcome") == "read",
        (signed.text[:300], team.text[:200], waited.get("status"), finished.get("status"), finished.get("error")),
    )

    # 4. An app's first address on a host nobody listed is held for a Security admin, nothing saved.
    # James (builder) holds no Security role, so his hosts wait for Security; Sam (Security admin) lists his own (4c).
    def custom_app(name: str, base: str, role: str = "builder") -> str:
        made = w.kept(w.gw.post("/v1/apps", json={"name": name, "authKind": "none"}, headers=w.who[role]))
        app_id = str((data(made) or {}).get("id") or "con_missing")
        w.kept(
            w.gw.patch(
                f"/v1/apps/{app_id}/accounts/{app_id}",
                json={"revision": (data(made) or {}).get("revision") or 1, "settings": {"baseUrl": base}},
                headers=w.who[role],
            )
        )
        return app_id

    def add_tool(app_id: str | None, name: str, base: str, role: str = "builder") -> Any:
        """A REST tool on `base`; with no app named, the tool's own custom app keeps the address (a builder's path)."""
        # Tool names are unique in the team, so each app's ping carries the app's name.
        op = f"ping_{name.lower().replace(' ', '_').replace('-', '_')}"
        tool = {"name": op, "description": "Ping.", "access": "read", "method": "GET", "url": f"{base}/ping"}
        body = {"name": name, "displayName": name, "type": "http", "http": tool}
        if app_id is not None:
            body["connectionId"] = app_id
        return w.gw.post("/v1/tool-modules", json=body, headers=w.who[role])

    def task(run_key: str) -> dict[str, Any]:
        listed = data(api.get("/reviews", params={"pageSize": 200}, headers=w.who["security"])) or {}
        rows = listed.get("data") if isinstance(listed, dict) else listed
        return next((r for r in rows or [] if r.get("id") == run_key), {})

    base = "https://unlisted.multi.test"
    unlisted = None
    held = add_tool(unlisted, "Unlisted desk", base)
    answer = data(held) or {}
    run_key = str(answer.get("runKey") or "")
    asked = task(run_key)
    check(
        "4 adding a tool on unlisted.multi.test is held for Security, and Human Tasks lists the host joined in",
        held.status_code == 202
        and answer.get("heldFor") == "security"
        and answer.get("host") == "unlisted.multi.test"
        and asked.get("kind") == "egress_host"
        and asked.get("status") == "pending"
        and (asked.get("egressHost") or {}).get("host") == "unlisted.multi.test"
        and (asked.get("egressHost") or {}).get("app") == "Unlisted desk"
        and add_tool(unlisted, "Unlisted desk", base).json().get("data", {}).get("runKey") == run_key,
        (held.status_code, held.text[:200], {k: asked.get(k) for k in ("id", "kind", "status", "egressHost")}),
    )

    # 4a. A Security admin approves: the host is listed in their name, and the retried add saves the tool.
    approved = api.post(f"/reviews/{run_key}/decision", json={"decision": "approved"}, headers=w.who["security"])
    hosts = (data(w.gw.get("/v1/egress", headers=w.who["admin"])) or {}).get("hosts") or []
    listed_by = {h.get("host"): h.get("addedBy") for h in hosts}.get("unlisted.multi.test")
    retried = add_tool(unlisted, "Unlisted desk", base)
    check(
        "4a Security approves; unlisted.multi.test is listed by the approver and the retried add saves the tool",
        approved.status_code == 200 and listed_by is not None and retried.status_code == 201,
        (approved.text[:200], listed_by, retried.status_code, retried.text[:200]),
    )

    # 4b. A Security admin refuses another host: a retry is refused with the reason, read against the run key.
    other = "https://refused.multi.test"
    refused_app = None
    second = data(add_tool(refused_app, "Refused desk", other)) or {}
    second_key = str(second.get("runKey") or "")
    why = "not a system the bank uses"
    no = api.post(
        f"/reviews/{second_key}/decision", json={"decision": "rejected", "reason": why}, headers=w.who["security"]
    )
    again = add_tool(refused_app, "Refused desk", other)
    error = (again.json() if again.status_code == 422 else {}).get("error") or {}
    check(
        "4b Security refuses refused.multi.test; a retry is refused with the reason and the run key",
        no.status_code == 200
        and (data(no) or {}).get("decisionReason") == why
        and again.status_code == 422
        and error.get("code") == "egress_host_refused"
        and why in str(error.get("message"))
        and second_key in str(error.get("message")),
        (second_key, no.text[:200], again.status_code, again.text[:300]),
    )

    # 4c. A Security admin's own app on a new host is listed in their name at once, with no task.
    mine = "https://listed.multi.test"
    sams = custom_app("Listed desk", mine, role="security")
    own = add_tool(sams, "listed-desk", mine, role="security")
    rows = data(api.get("/reviews", params={"pageSize": 200}, headers=w.who["security"])) or {}
    asked_sam = [
        r
        for r in (rows.get("data") if isinstance(rows, dict) else rows) or []
        if (r.get("egressHost") or {}).get("host") == "listed.multi.test"
    ]
    hosts = (data(w.gw.get("/v1/egress", headers=w.who["admin"])) or {}).get("hosts") or []
    check(
        "4c Sam (Security admin) adds a tool on listed.multi.test: saved at once, listed in his name, no task",
        own.status_code == 201
        and asked_sam == []
        and {h.get("host"): h.get("addedBy") for h in hosts}.get("listed.multi.test") == "Sam Adeyemi",
        (own.status_code, own.text[:200], len(asked_sam)),
    )

finish()
