"""uc-628, api layer: docs/usecases/tools-service/turn-on-in-one-window.md, stories S1 and S2.

platform-service signs the seeded people in; tools-service runs with the Salesforce and GitHub plugins
(OPS_PLUGINS_REPO, else the ops-ai-plugins repository beside ops-ai) and Ops AI's own app for each (OPS_PLUGIN_CLIENTS);
agents-service runs beside it for the team's assistant. Salesforce signs in against the fake Salesforce
(docs/usecases/lib/fake_salesforce.py) on its My Domain. No model call."""

from __future__ import annotations

import json
from contextlib import ExitStack
from typing import Any

from fake_salesforce import salesforce
from usecase_harness import PLUGINS_REPO
from usecase_harness import (
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    agents,
    bearer,
    check,
    data,
    finish,
    platform,
    signed_in,
    tools,
)

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
PLUGINS = PLUGINS_REPO / "plugins"
SALESFORCE = PLUGINS / "salesforce/src/ops_plugin_salesforce"
GITHUB = PLUGINS / "github/src/ops_plugin_github"
SF, GH = "plugin:opsai.salesforce", "plugin:opsai.github"
CLIENTS = {"opsai.salesforce": {"id": "ops-ai-acme", "secret": "acme-app"}, "opsai.github": {"id": "gh", "secret": "x"}}


def reads(page: dict[str, Any]) -> list[str]:
    return sorted(str(t["name"]) for t in page.get("tools") or [] if t.get("access") == "read" and t.get("added"))


with ExitStack() as stack:
    sf = stack.enter_context(salesforce())
    api, _ = stack.enter_context(platform())
    plugins = {
        "OPS_PLUGINS": "true",
        "OPS_PLUGIN_PATHS": json.dumps([str(SALESFORCE), str(GITHUB)]),
        "OPS_PLUGIN_CLIENTS": json.dumps(CLIENTS),
    }
    gw = stack.enter_context(
        tools({**sf["settings"], **AUTH, **plugins, "OPS_CONSOLE_URL": "https://console.acme.test"})
    )
    runtime = stack.enter_context(agents(gateway_url=str(gw.base_url).rstrip("/"), env=AUTH))
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    priya = bearer(signed_in(api, "p.shah@harborpine.example"), "team_ops")
    james = bearer(signed_in(api, "j.richardson@harborpine.example"), "team_ops")
    ravi = bearer(signed_in(api, "r.menon@harborpine.example"), "team_ops")
    gw.post("/v1/egress/ranges", json={"value": sf["range"], "note": "uc-628"}, headers=sam)

    # 1. S1: the window's answer turns Salesforce on: each person's own account with the team account for runs
    # nobody started, the sign-in address kept as a default on Ops AI's auth config, and the read tools added.
    body = {"enabled": True, "signIn": "person_or_team", "settings": {"login_url": sf["login_url"]}}
    on = gw.put(f"/v1/apps/{SF}/team", json=body, headers=priya)
    card = data(on) or {}
    page = data(gw.get(f"/v1/apps/{SF}", headers=priya)) or {}
    config = next((c for c in page.get("authConfigs") or [] if c.get("type") == "ops_ai"), {})
    place = next((f for f in config.get("fields") or [] if f.get("name") == "login_url"), {})
    account = data(gw.get(f"/v1/apps/{SF}/accounts/{card.get('connectionId')}", headers=priya)) or {}
    check(
        "1 Turn on Salesforce: the address is a default on Ops AI's auth config, each person's own account with the team "
        "account for unattended runs, and every read tool added",
        on.status_code == 200 and (place.get("value"), place.get("mode")) == (sf["login_url"], "default")
        and card.get("toolsAdded") == len(reads(page)) > 0 and account.get("signIn") == "person_or_team",
        {"place": (place.get("value"), place.get("mode")), "added": card.get("toolsAdded"), "reads": len(reads(page)),
         "signIn": account.get("signIn"), "configs": [(c.get("type"), c.get("fields")) for c in page.get("authConfigs") or []]},
    )  # fmt: skip

    # 2. S1: the team's assistant gets exactly the app's read tools, published at once; a second time changes nothing.
    gave = runtime.post("/v1/team-assistant/app-tools", json={"moduleIds": card.get("moduleIds") or []}, headers=priya)
    given = data(gave) or {}
    again = data(runtime.post("/v1/team-assistant/app-tools", json={"moduleIds": card.get("moduleIds")}, headers=priya))
    check(
        "2 the team's assistant gets Salesforce's read tools at once, and asking again changes nothing",
        gave.status_code == 200 and given.get("state") == "given" and sorted(given.get("tools") or []) == reads(page)
        and (again or {}).get("state") == "already",
        {"state": given.get("state"), "tools": len(given.get("tools") or []), "reads": len(reads(page)), "again": (again or {}).get("state")},
    )  # fmt: skip

    # 3. S1: the same for GitHub, whose read tools are its own.
    gh_on = gw.put(f"/v1/apps/{GH}/team", json={"enabled": True, "signIn": "person_or_team"}, headers=priya)
    gh_page = data(gw.get(f"/v1/apps/{GH}", headers=priya)) or {}
    gh_gave = data(runtime.post("/v1/team-assistant/app-tools", json={"moduleIds": (data(gh_on) or {}).get("moduleIds")}, headers=priya))  # fmt: skip
    check(
        "3 Turn on GitHub adds its read tools and gives them to the assistant, never its write tool",
        gh_on.status_code == 200 and (gh_gave or {}).get("state") == "given"
        and sorted((gh_gave or {}).get("tools") or []) == reads(gh_page) and "github_add_comment" not in (gh_gave or {}).get("tools", []),
        {"on": gh_on.text[:200], "gave": gh_gave, "reads": reads(gh_page)},
    )  # fmt: skip

    # 4. S1: someone who may not manage the team's apps or edit its agents is refused, and nothing changes.
    refused_on = gw.put(f"/v1/apps/{GH}/team", json={"enabled": False}, headers=ravi)
    refused_give = runtime.post("/v1/team-assistant/app-tools", json={"moduleIds": ["x"]}, headers=ravi)
    check(
        "4 a viewer can neither turn an app on or off nor change the assistant's tools",
        refused_on.status_code == 403 and refused_give.status_code == 403,
        {"on": refused_on.text[:200], "give": refused_give.text[:200]},
    )

    # 5. S2: the admin signs the team account in at the org's My Domain; the org address comes from the token.
    started = gw.post(
        f"/v1/apps/{SF}/accounts/{card.get('connectionId')}/sign-in", json={"account": "team"}, headers=priya
    )
    back = sf["sign_in"]((data(started) or {}).get("authorizeUrl", ""), "acme.integration")
    done = gw.post(
        "/v1/sign-ins/complete", json={"state": back.get("state", ""), "code": back.get("code", "")}, headers=priya
    )
    signed = data(gw.get(f"/v1/apps/{SF}", headers=priya)) or {}
    row = next((a for a in signed.get("accounts") or [] if a.get("default")), {})
    org = next((v.get("value") for v in row.get("signInValues") or [] if v.get("kind") == "found"), None)
    check(
        "5 the team account signs in at the My Domain and the account shows the org address from the token",
        done.status_code == 200 and org == sf["api_base"] and row.get("state") == "connected",
        {"done": done.text[:200], "row": {k: row.get(k) for k in ("state", "signInValues")}},
    )

    # 6. S2: a person with no Salesforce account of their own is asked to connect it: the team account is never used.
    headers = {**james, "X-Team-Id": "team_ops"}
    call = runtime.post("/v1/chat/threads", json={"kbIds": []}, headers=headers)
    query = gw.get("/v1/me/accounts", params={"every": "true"}, headers=james)
    mine = next((a for a in data(query) or [] if a.get("appId") == SF), {})
    check(
        "6 James holds no Salesforce sign-in of his own after the turn-on: the app is on, his own account is not connected",
        call.status_code in (200, 201) and query.status_code == 200 and mine and not mine.get("connected"),
        {"thread": call.text[:120], "mine": mine, "all": (data(query) or [])[:3]},
    )

finish()
