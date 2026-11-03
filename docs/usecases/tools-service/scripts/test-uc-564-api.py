"""uc-564, api layer: docs/usecases/tools-service/a-team-turns-on-the-salesforce.md, stories S1 (steps 1-7) and S4
(steps 8-12) and S6 (steps 24-28). platform-service signs the seeded people in; tools-service runs with plugins on
(OPS_PLUGINS), loads the Salesforce plugin from the ops-ai-plugins repository beside ops-ai (OPS_PLUGIN_PATHS) and
takes the API version every team uses from the install config (OPS_PLUGIN_LOCKED); the fake Salesforce (docs/usecases/lib/fake_salesforce.py)
signs each team in and answers its API, recording each query and the OAuth app each sign-in used. No model call."""

from __future__ import annotations

import json
import time
from contextlib import ExitStack
from typing import Any
from uuid import uuid4

import httpx
from apps_layer import run_path
from fake_salesforce import LIST_VIEW_ID, salesforce
from usecase_harness import (
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    agents,
    bearer,
    check,
    data,
    finish,
    platform,
    service_headers,
    signed_in,
    tools,
    until,
)
from usecase_harness import ROOT as REPO

PLUGIN = "opsai.salesforce"
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
CLIENT_SECRET = "acme-connected-app-secret"
PLATFORM_CLIENT = "ops-ai-platform"
PLATFORM_SECRET = "ops-ai-platform-app-secret"
SALESFORCE = REPO.parent / "ops-ai-plugins/plugins/salesforce/src/ops_plugin_salesforce"
PLUGINS = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps([str(SALESFORCE)])}
# Ops AI's own OAuth app for Salesforce: the install's, from its config, as a deployment sets it.
INSTALL_CLIENT = {"OPS_PLUGIN_CLIENTS": json.dumps({PLUGIN: {"id": PLATFORM_CLIENT, "secret": PLATFORM_SECRET}})}
# The API version the install fixes for every team, from its config.
LOCKED = {"OPS_PLUGIN_LOCKED": json.dumps({PLUGIN: {"api_version": "61.0"}})}
QUERY = "SELECT Id, CaseNumber, Status FROM Case WHERE CaseNumber = '00044818'"


TENANT: dict[str, str] = {}
INNER: dict[str, httpx.Client] = {}


def call(
    gw: httpx.Client, tool: str, args: dict[str, Any], team: str = "team_ops", acting_for: str | None = None
) -> httpx.Response:
    """A gateway call as agents-service makes it for a run in `team`: a read, so it runs at once. With `acting_for`
    (an email) it carries the acting-for token platform-service signs for that person, as a run a person started."""
    headers = service_headers("tools", tenant=TENANT["id"], service="agents", team=team)
    if acting_for:
        minted = INNER["api"].post(
            "/v1/acting-for-tokens",
            json={"email": acting_for},
            headers=service_headers("platform", tenant=TENANT["id"], service="agents", team=team),
        )
        headers["X-Acting-For"] = str((data(minted) or {}).get("token") or "")
    body = {"tool": tool, "input": args, "key": uuid4().hex, "runContext": {"environment": "production"}}
    return gw.post("/v1/calls", json=body, headers=headers | {"X-Team-Id": team})


def code_of(r: httpx.Response) -> str:
    try:
        return str(r.json().get("error", {}).get("code") or "")
    except ValueError:
        return ""


def grantable(gw: httpx.Client, team: str = "team_ops") -> set[str]:
    headers = service_headers("tools", tenant=TENANT["id"], service="agents", scopes=["tools:view"], team=team)
    rows = data(gw.get("/v1/grantable-operations", headers=headers | {"X-Team-Id": team})) or []
    return {str(r["name"]) for r in rows}


def sign_in_team(gw: httpx.Client, sf: dict[str, Any], who: dict[str, str], connection_id: str) -> httpx.Response:
    started = gw.post(f"/v1/connections/{connection_id}/sign-in", json={"environment": "production"}, headers=who)
    back = (
        sf["sign_in"]((data(started) or {}).get("authorizeUrl", ""), "acme.integration")
        if started.status_code == 200
        else {}
    )
    if not back.get("code"):
        print(f"sign-in gave no code: start {started.status_code} {started.text[:300]}; back {back}", flush=True)
    return gw.post(
        f"/v1/connections/{connection_id}/sign-in/complete",
        json={"state": back.get("state", ""), "code": back.get("code", "")},
        headers=who,
    )


with ExitStack() as stack:
    sf = stack.enter_context(salesforce())
    api, INNER["api"] = stack.enter_context(platform())
    gw = stack.enter_context(
        tools(
            {
                **sf["settings"],
                **AUTH,
                **PLUGINS,
                **INSTALL_CLIENT,
                **LOCKED,
                "OPS_CONSOLE_URL": "https://console.acme.test",
            }
        )
    )
    # agents-service on the scripted model, for step 45's chat turn; its tools come from this tools-service.
    chat = stack.enter_context(agents(gateway_url=str(gw.base_url).rstrip("/"), env=AUTH))
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    priya_session = signed_in(api, "p.shah@harborpine.example")
    priya = bearer(priya_session, "team_ops")
    TENANT["id"] = str((priya_session.get("principal") or {}).get("tenantId") or priya_session.get("tenantId") or "")
    james = bearer(signed_in(api, "j.richardson@harborpine.example"), "team_ops")
    wanjiru = bearer(signed_in(api, "w.kamau@harborpine.example"), "team_platform")

    # 1. Installed, Salesforce is listed for the team with no admin step, off until the team turns it on, and the
    # API version the install config fixes reads as locked.
    shown_plugins = (data(gw.get("/v1/plugins", headers=priya)) or {}).get("plugins", [])
    view = next((p for p in shown_plugins if p.get("id") == PLUGIN), {})
    check(
        "1 Salesforce is listed for the team with no install step, and its API version is fixed by the install",
        bool(view) and view.get("teamOn") is False and "api_version" in (view.get("locked") or []),
        {"view": str(view)[:300]},
    )

    # 2. The team admin turns it on for the team with the team's OAuth app; a builder cannot, nor change a locked field.
    login = sf["authorize_url"].rsplit("/", 1)[0]
    team_on = {
        "enabled": True,
        "settings": {"login_url": login},
        "clientId": "ops-ai-acme",
        "clientSecret": CLIENT_SECRET,
    }
    refused = gw.put(f"/v1/plugins/{PLUGIN}/team", json=team_on, headers=james)
    turned = gw.put(f"/v1/plugins/{PLUGIN}/team", json=team_on, headers=priya)
    view = data(turned) or {}
    locked = gw.put(
        f"/v1/plugins/{PLUGIN}/team", json={"enabled": True, "settings": {"api_version": "50.0"}}, headers=priya
    )
    check(
        "2 the team admin turns it on, its connection is made, and a locked field cannot be changed by the team",
        turned.status_code == 200
        and bool(view.get("connectionId"))
        and refused.status_code == 403
        and locked.status_code == 400
        and code_of(locked) == "setting_locked"
        and view.get("settings", {}).get("api_version") == "61.0",
        {"turned": turned.text[:300], "builder": refused.status_code, "locked": locked.text[:200]},
    )
    connection_id = str(view.get("connectionId") or "con_missing")

    # 3. Security lists the sign-in host and the instance the token will name, as for any outside system.
    allowed = [gw.post("/v1/egress/hosts", json={"value": h, "note": "uc-564"}, headers=sam) for h in sf["hosts"]]
    allowed.append(gw.post("/v1/egress/ranges", json={"value": sf["range"], "note": "uc-564"}, headers=sam))
    check("3 Security lists Salesforce's hosts", all(r.status_code in (200, 201, 409) for r in allowed))

    # 4. A token naming a host outside Salesforce is refused, and nothing is stored from it.
    sf["fake"].bad_instance = True
    bad = sign_in_team(gw, sf, priya, connection_id)
    sf["fake"].bad_instance = False
    still = data(gw.get("/v1/plugins", headers=priya)) or {}
    instance = (
        next((p for p in still.get("plugins", []) if p["id"] == PLUGIN), {}).get("settings", {}).get("instance_url")
    )
    check(
        "4 a sign-in whose token names a host outside Salesforce is refused and no instance is kept",
        bad.status_code == 400 and "evil.example" in bad.text and instance is None,
        {"status": bad.status_code, "text": bad.text[:300], "instance": instance},
    )

    # 5. The team signs in with its account; the instance comes from the token.
    done = sign_in_team(gw, sf, priya, connection_id)
    after = data(gw.get("/v1/plugins", headers=priya)) or {}
    mine = next((p for p in after.get("plugins", []) if p["id"] == PLUGIN), {})
    check(
        "5 the team signs in and the instance is read from Salesforce's token answer",
        done.status_code == 200 and mine.get("settings", {}).get("instance_url") == sf["api_base"],
        {"status": done.status_code, "text": done.text[:200], "settings": mine.get("settings")},
    )

    # 51. The team account reads connected at once, and its test runs on its own right after the sign-in.
    def team_row() -> dict[str, Any]:
        page = data(gw.get(f"/v1/apps/plugin:{PLUGIN}", headers=priya)) or {}
        return next((a for a in page.get("accounts") or [] if a.get("id") == connection_id), {})

    first_row = team_row()
    team_test = until(lambda: (team_row().get("test") or {}).get("status"), timeout=20)
    check(
        "51 the team account is connected right after its sign-in, and its own test ran and passed",
        first_row.get("state") == "connected" and team_test == "ok",
        {"first": first_row, "later": team_row()},
    )

    # 6. Test connection runs the plugin's health check, Salesforce's limits call, and passes.
    tested = gw.post(f"/v1/connections/{connection_id}/test", json={"environment": "production"}, headers=priya)
    health = (data(tested) or {}).get("health") or {}
    check(
        "6 Test connection runs the limits call and passes",
        tested.status_code == 200 and health.get("status") in ("ok", "healthy", "passed"),
        {"status": tested.status_code, "health": health, "text": tested.text[:300]},
    )

    # 7. The OAuth client secret is kept as a reference: no answer about the connection or the plugin shows it.
    shown = gw.get(f"/v1/connections/{connection_id}", headers=priya).text + gw.get("/v1/plugins", headers=priya).text
    check("7 the client secret is never shown back", bool(shown) and CLIENT_SECRET not in shown)

    # 8. A read runs at once through the plugin and reaches the team's instance with the SOQL the agent gave.
    read = call(gw, "salesforce_query", {"q": QUERY})
    out = (data(read) or {}).get("output") or {}
    queries = sf["fake"].state()["queries"]
    check(
        "8 salesforce_query runs at once and Salesforce receives the query as given",
        read.status_code == 200 and out.get("records", [{}])[0].get("CaseNumber") == "00044818" and QUERY in queries,
        {"status": read.status_code, "output": str(out)[:300], "queries": queries[-2:]},
    )

    # 9. The team admin turns it off: its tools leave the list, a call is refused; the connection is kept.
    off = gw.put(f"/v1/plugins/{PLUGIN}/team", json={"enabled": False}, headers=priya)
    listed_off = grantable(gw)
    refused_off = call(gw, "salesforce_query", {"q": QUERY})
    check(
        "9 turned off for the team, its tools leave the list and a call is refused with PLUGIN_DISABLED",
        off.status_code == 200
        and not any(n.startswith("salesforce_") for n in listed_off)
        and refused_off.status_code == 403
        and code_of(refused_off) == "PLUGIN_DISABLED",
        {"off": off.status_code, "refused": refused_off.text[:200]},
    )

    # 10. On again: the same connection and settings, and calls work with no new sign-in.
    again = data(gw.put(f"/v1/plugins/{PLUGIN}/team", json={"enabled": True}, headers=priya)) or {}
    works = call(gw, "salesforce_query", {"q": QUERY})
    check(
        "10 turned on again, it keeps its connection and settings and calls work without a new sign-in",
        again.get("connectionId") == connection_id
        and again.get("settings", {}).get("instance_url") == sf["api_base"]
        and bool(((data(works) or {}).get("output") or {}).get("records"))
        and "salesforce_query" in grantable(gw),
        {"again": again, "works": works.status_code},
    )

    # 40-42 (group D): the app's tools on its page, and a tool run from the tool page.
    page = data(gw.get(f"/v1/apps/plugin:{PLUGIN}", headers=priya)) or {}
    tools_on_page = {t.get("name"): t.get("title") for t in page.get("tools") or []}
    module = str(((page.get("card") or {}).get("moduleIds") or ["mod_missing"])[0])
    run = run_path(module, "salesforce_query")
    check(
        "40 the app's page lists its tools by name and title",
        bool(tools_on_page.get("salesforce_query")) and tools_on_page["salesforce_query"] != "salesforce_query",
        tools_on_page,
    )

    # 41. A Mock run answers from the tool's mock and nothing reaches Salesforce.
    sent_before = len(sf["fake"].state()["queries"])
    mocked = gw.post(run, json={"mode": "mock", "input": {"q": QUERY}}, headers=james)
    check(
        "41 a Mock run answers without reaching Salesforce",
        mocked.status_code == 200
        and (data(mocked) or {}).get("mocked") is True
        and len(sf["fake"].state()["queries"]) == sent_before,
        ("target: waits on P1", mocked.text[:200]),
    )

    # 42. A Real run goes through the gateway's checks with the team's account and reaches Salesforce.
    # It names no environment: the team signed in for production only (step 5), so the run uses production.
    real = gw.post(run, json={"mode": "real", "input": {"q": QUERY}}, headers=james)
    records = ((data(real) or {}).get("output") or {}).get("records") or [{}]
    check(
        "42 a Real run reads the case with the team's account through the gateway, and the call is logged",
        real.status_code == 200
        and records[0].get("CaseNumber") == "00044818"
        and bool((data(real) or {}).get("callId"))
        and QUERY in sf["fake"].state()["queries"][sent_before:],
        ("target: waits on P1", real.text[:300]),
    )

    # 50. A paged tool with a transform runs Real from its page: the answer is shaped once, as an agent gets it, and the
    # page shows the request that was sent.
    view_run = run_path(module, "salesforce_list_view")
    listed = gw.post(view_run, json={"mode": "real", "input": {"list_view": LIST_VIEW_ID}}, headers=james)
    shown = data(listed) or {}
    view_rows = (shown.get("output") or {}).get("records") if isinstance(shown.get("output"), dict) else None
    sent = shown.get("request") or {}
    check(
        "50 a paged tool's Real run shapes its answer once and shows the request it sent",
        listed.status_code == 200
        and not shown.get("transformError")
        and bool(view_rows)
        and isinstance(view_rows[0].get("fields"), dict)
        and LIST_VIEW_ID in str(sent.get("url") or ""),
        {"status": listed.status_code, "answer": listed.text[:400]},
    )

    # 45 (S7). A grant saved while an older publish request waits is what goes live, and chat offers it at
    # once: the request for the newest draft replaces the waiting one, Maya approves it, and the first turn calls it.
    maya = bearer(signed_in(api, "m.okafor@harborpine.example"), "team_ops")
    # Every agent publish in team_ops waits for review here, so the first request is still waiting at the second.
    policy = api.put("/v1/policies/publishReview", json={"value": {"agents": "always"}}, headers=priya)
    helper = data(chat.post("/v1/agents", json={"name": "Case desk", "role": "Finds cases"}, headers=james)) or {}
    first = (
        data(chat.patch(f"/v1/agents/{helper.get('id')}", json={"instructions": "Find cases."}, headers=james)) or {}
    )
    waiting = chat.post(
        f"/v1/agents/{helper.get('id')}/publish-requests", json={"version": first.get("version")}, headers=james
    )
    granted = data(chat.patch(f"/v1/agents/{helper.get('id')}", json={"toolIds": ["salesforce_query"]}, headers=james))
    asked = chat.post(
        f"/v1/agents/{helper.get('id')}/publish-requests",
        json={"version": (granted or {}).get("version")},
        headers=james,
    )
    # The team's policy may publish the newest draft at once (its builder holds the reviewer role); else Maya approves.
    if (data(asked) or {}).get("status") != "approved":
        chat.post(
            f"/v1/publish-requests/{(data(asked) or {}).get('id')}/decision",
            json={"decision": "approved"},
            headers=maya,
        )
    old = data(chat.get(f"/v1/publish-requests/{(data(waiting) or {}).get('id')}", headers=maya)) or {}
    thread = data(chat.post("/chat/threads", json={"agentId": helper.get("id"), "kbIds": []}, headers=james)) or {}
    turn = chat.post(
        f"/chat/threads/{thread.get('id')}/messages",
        json={"content": f'call salesforce_query {{"q": "{QUERY}"}}'},
        headers=james | {"Accept": "text/event-stream"},
    )
    check(
        "45 the request for the newest draft replaces the waiting one, and after Maya approves it the first chat turn "
        "calls the newly granted salesforce_query",
        (data(waiting) or {}).get("status") == "pending"
        and asked.status_code == 201
        and old.get("status") == "returned"
        and "salesforce_query" in turn.text
        and '"totalSize": 1' in turn.text,
        {
            "policy": policy.text[:160],
            "waiting": (data(waiting) or {}).get("status"),
            "asked": (asked.status_code, (data(asked) or {}).get("status")),
            "old": old.get("status"),
            "turn": turn.text[-300:],
        },
    )

    # 11. The team admin turns it off for the team: a call is refused at once, with no restart; on again, it runs.
    team_off = gw.put(f"/v1/plugins/{PLUGIN}/team", json={"enabled": False}, headers=priya)
    stopped = call(gw, "salesforce_query", {"q": QUERY})
    team_back = gw.put(f"/v1/plugins/{PLUGIN}/team", json={"enabled": True}, headers=priya)
    back = call(gw, "salesforce_query", {"q": QUERY})
    check(
        "11 off for the team, a call is refused with PLUGIN_DISABLED; on again, it runs",
        team_off.status_code == 200
        and code_of(stopped) == "PLUGIN_DISABLED"
        and team_back.status_code == 200
        and bool(((data(back) or {}).get("output") or {}).get("records")),
        {
            "off": team_off.status_code,
            "stopped": stopped.text[:200],
            "on": team_back.status_code,
            "back": back.status_code,
        },
    )

    # 12. Nobody edits, publishes or deletes the plugin's module, the team admin included.
    patched = gw.patch("/v1/tool-modules/mod_plugin_salesforce", json={"description": "mine now"}, headers=priya)
    deleted = gw.delete("/v1/tool-modules/mod_plugin_salesforce", headers=priya)
    check(
        "12 the plugin's module refuses an edit and a delete (plugin_module)",
        code_of(patched) == "plugin_module" and code_of(deleted) == "plugin_module",
        {"patch": patched.text[:200], "delete": deleted.text[:200]},
    )

    # 24. Ops AI's own OAuth app is the install's: teams see its client id, no route sets its secret, and no answer
    # carries the secret.
    by_admin = gw.put(f"/v1/plugins/{PLUGIN}/app-secret", json={"clientSecret": "other"}, headers=sam)
    listed = gw.get("/v1/plugins", headers=priya)
    view = next((p for p in (data(listed) or {}).get("plugins", []) if p["id"] == PLUGIN), {})
    check(
        "24 Ops AI's own OAuth app comes from the install config; no route sets its secret",
        by_admin.status_code in (404, 405)
        and view.get("platformApp") == {"clientId": PLATFORM_CLIENT, "secretSet": True}
        and PLATFORM_SECRET not in listed.text,
        {"set": by_admin.status_code, "view": view.get("platformApp")},
    )

    # 25. A second team turns Salesforce on with no app of its own. Until it signs in, its calls never run on another
    # team's account, though team_ops is signed in to the same instance.
    time.sleep(6)
    other = gw.put(
        f"/v1/plugins/{PLUGIN}/team", json={"enabled": True, "settings": {"login_url": login}}, headers=wanjiru
    )
    other_id = str((data(other) or {}).get("connectionId") or "con_missing")
    asked = len(sf["fake"].state()["queries"])
    unsigned = call(gw, "salesforce_query", {"q": QUERY}, team="team_platform")
    check(
        "25 a second team's call before it signs in is refused and never runs on another team's account",
        other.status_code == 200 and unsigned.status_code != 200 and len(sf["fake"].state()["queries"]) == asked,
        {"on": other.text[:200], "call": unsigned.status_code, "code": code_of(unsigned), "text": unsigned.text[:200]},
    )

    # 26. It signs in through the platform's app: the token exchange carries the platform's client id and secret.
    signed = sign_in_team(gw, sf, wanjiru, other_id)
    used = sf["fake"].state()["clients"][-1:]
    worked = call(gw, "salesforce_query", {"q": QUERY}, team="team_platform")
    check(
        "26 a team with no app of its own signs in with the platform's, and its calls run",
        signed.status_code == 200
        and used == [(PLATFORM_CLIENT, PLATFORM_SECRET)]
        and bool(((data(worked) or {}).get("output") or {}).get("records")),
        {"sign-in": signed.text[:200], "client": [c for c, _ in used], "call": worked.status_code},
    )

    # 27. A team that brought its own app keeps it after the platform has one.
    resigned = sign_in_team(gw, sf, priya, connection_id)
    own = sf["fake"].state()["clients"][-1:]
    check(
        "27 a team's own OAuth app wins over the platform's",
        resigned.status_code == 200 and own == [("ops-ai-acme", CLIENT_SECRET)],
        {"sign-in": resigned.status_code, "client": [c for c, _ in own]},
    )

    # 28. No answer shows the platform's secret, to either team or to the platform admin.
    reads = [
        gw.get("/v1/plugins", headers=sam),
        gw.get("/v1/plugins", headers=wanjiru),
        gw.get(f"/v1/connections/{other_id}", headers=wanjiru),
        gw.get("/v1/connections", headers=wanjiru),
    ]
    check(
        "28 the platform's secret is never shown back",
        all(r.status_code == 200 for r in reads) and not any(PLATFORM_SECRET in r.text for r in reads),
        [r.status_code for r in reads],
    )

    # 47. A third team turns Salesforce on with each person signing in with their own account, and no team account.
    # Before Sam signs in, his call asks for his own sign-in; it is not refused as the app being off.
    security = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    mine_on = gw.put(
        f"/v1/plugins/{PLUGIN}/team",
        json={"enabled": True, "signIn": "person", "settings": {"login_url": login}},
        headers=security,
    )
    mine_id = str((data(mine_on) or {}).get("connectionId") or "con_missing")
    before = call(gw, "salesforce_query", {"q": QUERY}, team="team_security", acting_for="s.adeyemi@harborpine.example")
    check(
        "47 on an app where each person signs in, a person's call before their sign-in asks them to sign in",
        mine_on.status_code == 200 and before.status_code == 403 and code_of(before) == "CONNECTION_NOT_LINKED",
        {"on": mine_on.text[:200], "call": before.status_code, "text": before.text[:300]},
    )

    # 48. Sam signs in with his own account; no team account exists, and the instance comes from his sign-in.
    own = gw.post(f"/v1/connections/{mine_id}/sign-in", json={"environment": "production"}, headers=security)
    back = sf["sign_in"]((data(own) or {}).get("authorizeUrl", ""), "sam.own") if own.status_code == 200 else {}
    own_done = gw.post(
        f"/v1/connections/{mine_id}/sign-in/complete",
        json={"state": back.get("state", ""), "code": back.get("code", "")},
        headers=security,
    )
    page_mine = data(gw.get(f"/v1/apps/plugin:{PLUGIN}", headers=security)) or {}
    accounts_mine = page_mine.get("accounts") or []
    check(
        "48 a person signs in with their own account before any team account exists",
        own_done.status_code == 200 and any(a.get("id") == mine_id and a.get("mine") for a in accounts_mine),
        {"start": own.text[:200], "done": own_done.text[:300], "accounts": accounts_mine},
    )

    # 49. His call now runs on his own account and reaches the instance his sign-in named.
    sent_before = len(sf["fake"].state()["queries"])
    after_own = call(
        gw, "salesforce_query", {"q": QUERY}, team="team_security", acting_for="s.adeyemi@harborpine.example"
    )
    rows = ((data(after_own) or {}).get("output") or {}).get("records") or [{}]
    check(
        "49 the person's call runs on their own account with no team account, and reaches Salesforce",
        after_own.status_code == 200
        and rows[0].get("CaseNumber") == "00044818"
        and QUERY in sf["fake"].state()["queries"][sent_before:],
        {"status": after_own.status_code, "text": after_own.text[:300]},
    )

finish()
