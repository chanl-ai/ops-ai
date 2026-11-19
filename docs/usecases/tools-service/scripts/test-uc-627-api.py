"""uc-627, api layer: docs/usecases/tools-service/salesforce-org-address.md, stories S1 and S2.

platform-service signs the seeded people in; tools-service runs with plugins on and the Salesforce plugin
(OPS_SALESFORCE_PLUGIN, else the ops-ai-plugins repository beside ops-ai) against the fake Salesforce
(docs/usecases/lib/fake_salesforce.py), whose orgs sign in at their own My Domain and name their address in the token
answer. Security lists the fake's private range only, never its hosts. Each tool call is a gateway call as
agents-service makes it for a run. No model call."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fake_salesforce import salesforce
from usecase_harness import PLUGINS_REPO
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

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
SALESFORCE = Path(
    os.environ.get("OPS_SALESFORCE_PLUGIN")
    or PLUGINS_REPO / "plugins/salesforce/src/ops_plugin_salesforce"
)
APP = "plugin:opsai.salesforce"
CASE = "SELECT Id, CaseNumber, Status FROM Case WHERE CaseNumber = '00044818'"
TENANT: dict[str, str] = {}
# Each run names its own sandbox account, as the stack's database keeps the last run's.
UAT = f"Kestrel UAT {uuid4().hex[:6]}"


def call(gw: httpx.Client, tool: str, args: dict[str, Any], account: str | None = None) -> httpx.Response:
    """A call as agents-service makes it for a run in team_ops with nobody behind it, on the account named `account`
    when given, else the default one."""
    headers = service_headers("tools", tenant=TENANT["id"], service="agents", team="team_ops")
    context: dict[str, Any] = {"environment": "live", **({"account": account} if account else {})}
    body: dict[str, Any] = {"tool": tool, "input": args, "key": uuid4().hex, "runContext": context}
    return gw.post("/v1/calls", json=body, headers=headers | {"X-Team-Id": "team_ops"})


def records(r: httpx.Response) -> list[dict[str, Any]]:
    got = data(r) if r.status_code == 200 else None
    out = dict((got or {}).get("output") or {}) if isinstance(got, dict) else {}
    return list(out.get("records") or [])


def sign_in(gw: httpx.Client, browser: Any, who: dict[str, str], account: str, user: str) -> tuple[str, httpx.Response]:
    """Plays the browser through the team sign-in of `account`; the address the sign-in opened, and its answer."""
    started = gw.post(f"/v1/apps/{APP}/accounts/{account}/sign-in", json={"account": "team"}, headers=who)
    opened = str((data(started) or {}).get("authorizeUrl") or "")
    back = browser(opened, user) if started.status_code == 200 else {}
    done = gw.post(
        "/v1/sign-ins/complete", json={"state": back.get("state", ""), "code": back.get("code", "")}, headers=who
    )
    return opened, done


def values_of(gw: httpx.Client, who: dict[str, str], account: str) -> dict[str, str]:
    """Where an account signs in and what its sign-in found, as its row on the app's Accounts list shows them."""
    page = data(gw.get(f"/v1/apps/{APP}", headers=who)) or {}
    row = next((a for a in page.get("accounts") or [] if a.get("id") == account), {})
    return {f"{v['kind']}:{v['name']}": str(v["value"]) for v in row.get("signInValues") or []}


manifest = (SALESFORCE / "plugin.yaml").read_text() if (SALESFORCE / "plugin.yaml").exists() else ""
with ExitStack() as stack:
    sf = stack.enter_context(salesforce())
    api, _ = stack.enter_context(platform())
    plugins = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps([str(SALESFORCE)])}
    gw = stack.enter_context(
        tools({**sf["settings"], **AUTH, **plugins, "OPS_CONSOLE_URL": "https://console.acme.test"})
    )
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    session = signed_in(api, "p.shah@harborpine.example")
    priya = bearer(session, "team_ops")
    TENANT["id"] = str((session.get("principal") or {}).get("tenantId") or session.get("tenantId") or "")
    fake = sf["fake"]
    # The fake answers on a private address, which egress refuses unless Security allows the range; its hosts are
    # never listed, so a call that reaches them was allowed by the plugin's own egress.
    gw.post("/v1/egress/ranges", json={"value": sf["range"], "note": "uc-627"}, headers=sam)
    org = sf["api_base"]

    # 1. S1: the team's own auth config holds the org's My Domain as its sign-in address, fixed.
    made = gw.post(
        "/v1/app-credentials",
        json={
            "app": APP,
            "name": "Kestrel org",
            "clientId": "ops-ai-acme",
            "clientSecret": "s3",
            "settings": {"login_url": sf["login_url"]},
        },
        headers=priya,
    )
    config = str((data(made) or {}).get("id") or "cred_missing")
    page = data(gw.get(f"/v1/apps/{APP}", headers=priya)) or {}
    held = next((c for c in page.get("authConfigs") or [] if c.get("id") == config), {})
    field = next((f for f in held.get("fields") or [] if f.get("name") == "login_url"), {})
    check(
        "1 the auth config holds the My Domain sign-in address, fixed, read as its host",
        made.status_code == 201 and field.get("value") == sf["login_url"] and field.get("mode") == "fixed"
        and field.get("shown") == urlsplit(org).hostname,
        {"made": made.text[:200], "field": field},
    )  # fmt: skip

    # 2-3. S1: Connect on it signs in at the My Domain, and the account keeps the org address the token answer named.
    on = gw.put(f"/v1/apps/{APP}/team", json={"enabled": True, "credentialId": config}, headers=priya)
    account = str((data(on) or {}).get("connectionId") or "con_missing")
    before = len(fake.state()["userinfo"])
    opened, done = sign_in(gw, sf["sign_in"], priya, account, "kestrel.integration")
    check(
        "2 Connect opens the sign-in at the org's My Domain",
        on.status_code == 200 and opened.startswith(f"{sf['login_url']}/authorize"),
        {"on": on.text[:200], "opened": opened[:200]},
    )
    found = values_of(gw, priya, account)
    check(
        "3 the sign-in finishes, and the account's org address is the token answer's instance_url, with no UserInfo call",
        done.status_code == 200 and found.get("found:instance_url") == org
        and found.get("place:login_url") == sf["login_url"] and len(fake.state()["userinfo"]) == before
        and "from_token" in manifest,
        {"done": done.text[:300], "found": found, "userinfo": fake.state()["userinfo"]},
    )  # fmt: skip

    # 4. S1: salesforce_query reaches the org address, through egress no one listed, and returns the case.
    queries = len(fake.state()["queries"])
    asked = call(gw, "salesforce_query", {"q": CASE})
    got = records(asked)
    check(
        "4 salesforce_query reaches the org address with no egress host listed and returns case 00044818",
        asked.status_code == 200
        and [r.get("CaseNumber") for r in got] == ["00044818"]
        and fake.state()["queries"][queries:] == [CASE],
        {"call": asked.text[:400]},
    )

    # 5-6. S2: a config whose address is a default; a second account signs in at the sandbox's My Domain instead, and
    # its calls reach the sandbox org.
    shared = gw.post(
        "/v1/app-credentials",
        json={"app": APP, "name": "Kestrel default", "clientId": "ops-ai-acme", "clientSecret": "s3",
              "settings": {"login_url": sf["login_url"]}, "modes": {"login_url": "default"}},
        headers=priya,
    )  # fmt: skip
    default = str((data(shared) or {}).get("id") or "cred_missing")
    second = gw.post(
        f"/v1/apps/{APP}/accounts",
        json={"name": UAT, "credentialId": default, "settings": {"login_url": sf["sandbox_login_url"]}},
        headers=priya,
    )
    uat = str((data(second) or {}).get("id") or "con_missing")
    opened_uat, done_uat = sign_in(gw, sf["sign_in"], priya, uat, "kestrel.uat")
    found_uat = values_of(gw, priya, uat)
    check(
        "5 an account on a default address signs in at the sandbox's My Domain, and keeps the sandbox's org address",
        second.status_code == 201 and opened_uat.startswith(f"{sf['sandbox_login_url']}/authorize")
        and done_uat.status_code == 200 and found_uat.get("found:instance_url") == sf["sandbox_base"],
        {"second": second.text[:200], "opened": opened_uat[:200], "done": done_uat.text[:300], "found": found_uat},
    )  # fmt: skip
    # The fake answers a token only at its own org's host, so a 200 here was a call to the sandbox's address.
    on_uat = call(gw, "salesforce_query", {"q": CASE}, account=UAT)
    check(
        "6 salesforce_query on the sandbox account reaches the sandbox org and returns the case",
        on_uat.status_code == 200 and [r.get("CaseNumber") for r in records(on_uat)] == ["00044818"],
        {"call": on_uat.text[:400], "refused": fake.state()["refused"]},
    )

finish()
