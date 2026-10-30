"""uc-564, api layer: docs/usecases/tools-service/a-team-turns-on-the-salesforce.md, stories S1 (steps 1-7) and S4
(steps 8-12) and S6 (steps 24-28). platform-service signs the seeded people in and holds the install switch (the
`plugins` policy); tools-service runs with plugins on (OPS_PLUGINS) and loads the Salesforce plugin from the
ops-ai-plugins repository beside ops-ai (OPS_PLUGIN_PATHS); the fake Salesforce (docs/usecases/lib/fake_salesforce.py)
signs each team in and answers its API, recording each query and the OAuth app each sign-in used. No model call."""

from __future__ import annotations

import json
import time
from contextlib import ExitStack
from typing import Any
from uuid import uuid4

import httpx
from fake_salesforce import salesforce
from usecase_harness import (
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    bearer,
    check,
    data,
    finish,
    platform,
    service_headers,
    signed_in,
    tools,
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
QUERY = "SELECT Id, CaseNumber, Status FROM Case WHERE CaseNumber = '00044818'"


TENANT: dict[str, str] = {}


def call(gw: httpx.Client, tool: str, args: dict[str, Any], team: str = "team_ops") -> httpx.Response:
    """A gateway call as agents-service makes it for a run in `team`: a read, so it runs at once."""
    headers = service_headers("tools", tenant=TENANT["id"], service="agents", team=team)
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


def install(api: httpx.Client, who: dict[str, str], on: bool, client: str | None = None) -> httpx.Response:
    value: dict[str, Any] = {PLUGIN: {"enabled": on, "locked": {"api_version": "61.0"}}}
    if client:
        value[PLUGIN]["client"] = {"id": client}
    return api.put("/v1/policies/plugins", json={"value": value}, headers=who)


with ExitStack() as stack:
    sf = stack.enter_context(salesforce())
    api, _ = stack.enter_context(platform())
    gw = stack.enter_context(
        tools({**sf["settings"], **AUTH, **PLUGINS, "OPS_CONSOLE_URL": "https://console.acme.test"})
    )
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    priya_session = signed_in(api, "p.shah@harborpine.example")
    priya = bearer(priya_session, "team_ops")
    TENANT["id"] = str((priya_session.get("principal") or {}).get("tenantId") or priya_session.get("tenantId") or "")
    james = bearer(signed_in(api, "j.richardson@harborpine.example"), "team_ops")
    wanjiru = bearer(signed_in(api, "w.kamau@harborpine.example"), "team_platform")

    # 1. The platform admin turns Salesforce on for the install and locks the API version; a builder cannot.
    by_builder = install(api, james, True)
    on = install(api, sam, True)
    check(
        "1 the platform admin turns Salesforce on for the install; a team builder is refused",
        on.status_code == 200 and by_builder.status_code == 403,
        {"admin": on.status_code, "builder": by_builder.status_code, "text": on.text[:200]},
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

    # 11. The platform admin turns it off for the install: every team's calls stop within seconds, with no restart.
    install(api, sam, False)
    time.sleep(6)
    stopped = call(gw, "salesforce_query", {"q": QUERY})
    install(api, sam, True)
    time.sleep(6)
    back = call(gw, "salesforce_query", {"q": QUERY})
    check(
        "11 off for the install, calls are refused within seconds; on again, they run",
        code_of(stopped) == "PLUGIN_DISABLED" and bool(((data(back) or {}).get("output") or {}).get("records")),
        {"stopped": stopped.text[:200], "back": back.status_code},
    )

    # 12. Nobody edits, publishes or deletes the plugin's module, the team admin included.
    patched = gw.patch("/v1/tool-modules/mod_plugin_salesforce", json={"description": "mine now"}, headers=priya)
    deleted = gw.delete("/v1/tool-modules/mod_plugin_salesforce", headers=priya)
    check(
        "12 the plugin's module refuses an edit and a delete (plugin_module)",
        code_of(patched) == "plugin_module" and code_of(deleted) == "plugin_module",
        {"patch": patched.text[:200], "delete": deleted.text[:200]},
    )

    # 24. The platform sets up its own OAuth app once: the client id in the install switch, the secret at the account.
    # A team admin cannot set it.
    by_team = gw.put(f"/v1/plugins/{PLUGIN}/app-secret", json={"clientSecret": PLATFORM_SECRET}, headers=priya)
    policy = install(api, sam, True, client=PLATFORM_CLIENT)
    secret = gw.put(f"/v1/plugins/{PLUGIN}/app-secret", json={"clientSecret": PLATFORM_SECRET}, headers=sam)
    check(
        "24 the platform admin sets up the platform's own OAuth app; a team admin cannot",
        by_team.status_code == 403 and policy.status_code == 200 and secret.status_code == 200,
        {"team admin": by_team.status_code, "policy": policy.text[:200], "secret": secret.text[:200]},
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

finish()
