"""uc-584, api layer: docs/usecases/tools-service/plugin-manifest-fields.md, stories S1 to S4.

Part one: platform-service signs the seeded people in; tools-service runs with plugins on
and the three test plugins in services/tools-service/tests/plugin_fields (OPS_PLUGIN_PATHS); the fake system
(docs/usecases/lib/fake_multi_auth.py) shows the headers it was sent, takes chat messages only as a form, counts
transfers, refuses the Zoom-style client unless it comes as basic auth, records each sign-in address and answers the
sites lookup. Part two: the Salesforce plugin (OPS_SALESFORCE_PLUGIN, else the ops-ai-plugins repository beside
ops-ai) against the fake Salesforce (docs/usecases/lib/fake_salesforce.py), which names its instance in the token answer, counts UserInfo calls
and records the query options each query-all carried. Each call is a gateway call as agents-service makes it for a
run. No model call."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fake_multi_auth import CLIENTS, SECRETS, SITE, digest, multi_auth
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
from usecase_harness import ROOT as REPO

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
FIELDS = REPO / "services/tools-service/tests/plugin_fields"
SALESFORCE = Path(
    os.environ.get("OPS_SALESFORCE_PLUGIN")
    or PLUGINS_REPO / "plugins/salesforce/src/ops_plugin_salesforce"
)
TENANT: dict[str, str] = {}
SEEN: list[str] = []


def kept(r: httpx.Response) -> httpx.Response:
    SEEN.append(r.text)
    return r


def call(gw: httpx.Client, tool: str, args: dict[str, Any] | None = None) -> httpx.Response:
    """A call as agents-service makes it for a run in team_ops with nobody behind it."""
    headers = service_headers("tools", tenant=TENANT["id"], service="agents", team="team_ops")
    body = {"tool": tool, "input": args or {}, "key": uuid4().hex, "runContext": {"environment": "live"}}
    return kept(gw.post("/v1/calls", json=body, headers=headers | {"X-Team-Id": "team_ops"}))


def output(r: httpx.Response) -> dict[str, Any]:
    got = data(r) if r.status_code == 200 else None
    return dict((got or {}).get("output") or {}) if isinstance(got, dict) else {}


def error(r: httpx.Response) -> dict[str, Any]:
    try:
        body = r.json()
    except ValueError:
        return {}
    found = (body.get("data") or {}).get("output", {}).get("error") if body.get("data") else body.get("error")
    return dict(found or {})


def credential(gw: httpx.Client, who: dict[str, str], plugin: str, client_id: str, secret: str | None = None) -> str:
    """The team's own OAuth client for `plugin`, made under Credentials with no account; its id, which a turn-on names
    as credentialId."""
    body = {"app": f"plugin:{plugin}", "clientId": client_id, **({"clientSecret": secret} if secret else {})}
    return str((data(kept(gw.post("/v1/app-credentials", json=body, headers=who))) or {}).get("id") or "cred_missing")


def turn_on(gw: httpx.Client, who: dict[str, str], plugin: str, **body: Any) -> httpx.Response:
    return kept(gw.put(f"/v1/apps/plugin:{plugin}/team", json={"enabled": True, **body}, headers=who))


def at(plugin: str, conn: str) -> str:
    """A plugin's account lives under its app."""
    return f"/v1/apps/plugin:{plugin}/accounts/{conn}"


def sign_in(
    gw: httpx.Client, browser: Any, who: dict[str, str], path: str, user: str, *, account: str = "self"
) -> tuple[httpx.Response, httpx.Response]:
    """Plays the browser through the sign-in of the account at `path`."""
    started = gw.post(f"{path}/sign-in", json={"account": account}, headers=who)
    back = browser((data(started) or {}).get("authorizeUrl", ""), user) if started.status_code == 200 else {}
    done = gw.post(
        "/v1/sign-ins/complete",
        json={"state": back.get("state", ""), "code": back.get("code", "")},
        headers=who,
    )
    return started, kept(done)


def calls_of(fake: Any, method: str) -> list[dict[str, Any]]:
    return [c for c in fake.state()["calls"] if c["method"] == method]


with ExitStack() as stack:
    m = stack.enter_context(multi_auth())
    fake = m["fake"]
    api, _ = stack.enter_context(platform())
    folders = sorted(str(p) for p in FIELDS.glob("fields_*"))
    plugins = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps(folders)}
    gw = stack.enter_context(
        tools({**m["settings"], **AUTH, **plugins, "OPS_CONSOLE_URL": "https://console.acme.test"})
    )
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    priya_session = signed_in(api, "p.shah@harborpine.example")
    priya = bearer(priya_session, "team_ops")
    TENANT["id"] = str((priya_session.get("principal") or {}).get("tenantId") or priya_session.get("tenantId") or "")
    james = bearer(signed_in(api, "j.richardson@harborpine.example"), "team_ops")

    # 1. The three test plugins load; Security lists the fake's hosts.
    loaded = data(gw.get("/v1/apps", headers=priya)) or []
    ids = sorted(str(c["pluginId"]) for c in loaded if c.get("kind") == "plugin")
    for h in m["hosts"]:
        gw.post("/v1/egress/hosts", json={"value": h, "note": "uc-584"}, headers=sam)
    gw.post("/v1/egress/ranges", json={"value": m["range"], "note": "uc-584"}, headers=sam)
    check(
        "1 the three test plugins load",
        {"test.fields", "test.fields-sites", "test.fields-zoom"} <= set(ids),
        {"ids": ids},
    )

    # 2. S1: a data tool carries the plugin's header and its own, beside the team's token, unchanged.
    on = turn_on(gw, priya, "test.fields", credentials={"token": SECRETS["token"]})
    # A new app hands agents its read tools only; the team admin adds the two writes, as from the app's Tools tab.
    gw.post(
        "/v1/apps/plugin:test.fields/tools", json={"tools": ["fields_post_message", "fields_transfer"]}, headers=priya
    )
    searched = call(gw, "fields_search", {"q": "card"})
    seen = (calls_of(fake, "fields") or [{}])[-1]
    check(
        "2 the system receives X-Api-Version and ConsistencyLevel on the search, and the team's own token beside them",
        on.status_code == 200 and searched.status_code == 200
        and seen.get("headers", {}).get("x-api-version") == "2026-10"
        and seen.get("headers", {}).get("consistencylevel") == "eventual"
        and seen.get("accepted") is True and seen.get("credential") == digest(SECRETS["token"]),
        {"on": on.text[:200], "call": searched.text[:300], "seen": seen},
    )  # fmt: skip

    # 3. S1: a Python tool's requests carry the plugin's header, and its answer never carries the token.
    echoed = call(gw, "fields_echo")
    sent = output(echoed).get("sent", {})
    check(
        "3 a Python tool's request carries the plugin's header, and what it returns holds no token",
        echoed.status_code == 200 and sent.get("x-api-version") == "2026-10" and SECRETS["token"] not in echoed.text,
        echoed.text[:300],
    )

    # 4. S1: a team setting a header would carry as a secret reference turns the team's calls off; nothing is sent.
    before = len(fake.state()["calls"])
    turn_on(gw, priya, "test.fields", settings={"api_version": "{{OPS_SECRETS_KEY}}"})
    poisoned = call(gw, "fields_search")
    after = len(fake.state()["calls"])
    turn_on(gw, priya, "test.fields", settings={"api_version": "2026-10"})
    check(
        "4 a team setting holding {{ turns the plugin's calls off naming the setting, and nothing reaches the system",
        error(poisoned).get("code") == "PLUGIN_DISABLED" and "api_version" in str(error(poisoned).get("message"))
        and after == before,
        {"call": poisoned.text[:300], "calls": (before, after)},
    )  # fmt: skip

    # 5. S2: a form tool's fields arrive form-encoded, as Slack's methods take them.
    posted = call(gw, "fields_post_message", {"channel": "C024BE91L", "text": "Card 1042 & more"})
    form_seen = (calls_of(fake, "fields") or [{}])[-1]
    check(
        "5 the chat method receives a form with the channel and the text, and accepts it",
        output(posted).get("ok") is True
        and output(posted).get("fields") == {"channel": "C024BE91L", "text": "Card 1042 & more"}
        and str(form_seen.get("headers", {}).get("content-type", "")).startswith("application/x-www-form-urlencoded"),
        {"call": posted.text[:300], "seen": form_seen},
    )

    # 6. S2: a transfer within its limit reaches the system; one over it, or with no amount, never leaves.
    within = call(gw, "fields_transfer", {"amount": 4999.5, "to": "acct-7"})
    count = len(fake.state()["transfers"])
    over = call(gw, "fields_transfer", {"amount": 5000.01, "to": "acct-7"})
    missing = call(gw, "fields_transfer", {"to": "acct-7"})
    check(
        "6 a transfer of 4999.50 is sent, one of 5000.01 is refused amount_over_limit and one without an amount 422, "
        "and the system sees only the first",
        output(within).get("amount") == 4999.5 and count == 1
        and error(over).get("code") == "amount_over_limit" and missing.status_code == 422
        and len(fake.state()["transfers"]) == 1,
        {"within": within.text[:300], "over": over.text[:300], "missing": missing.text[:300]},
    )  # fmt: skip

    # 7. S3: a Zoom-style token call sends the client as basic auth, never in the form, and the call runs.
    zoom = turn_on(
        gw,
        priya,
        "test.fields-zoom",
        credentialId=credential(gw, priya, "test.fields-zoom", "multi-zoom", CLIENTS["multi-zoom"]),
    )
    zoomed = call(gw, "fields_zoom_get_record", {"id": "rec-1042"})
    asked = [r for r in fake.state()["token_requests"] if r["client"] == "multi-zoom"]
    check(
        "7 every token request for the Zoom-style app sends its client as basic auth, and the call reaches the system",
        zoom.status_code == 200 and output(zoomed).get("as") == "client"
        and bool(asked) and all(r["sent_as"] == "basic" and r["accepted"] for r in asked),
        {"on": zoom.text[:200], "call": zoomed.text[:300], "asked": asked},
    )  # fmt: skip

    # 8. S3 and S4: the team's sign-in address carries the plugin's parameters and not one of the platform's own is
    # replaced; the lookup after sign-in finds the site, and the call reaches it.
    sites_on = turn_on(gw, priya, "test.fields-sites", signIn="person_or_team", credentialId=credential(gw, priya, "test.fields-sites", "multi-app", CLIENTS["multi-app"]))  # fmt: skip
    sites_id = str((data(sites_on) or {}).get("connectionId") or "con_missing")
    # The team's account signs the calls a run makes with nobody behind it (the team backup).
    sites = f"/v1/apps/plugin:test.fields-sites/accounts/{sites_id}"
    held = data(gw.get(sites, headers=priya)) or {}
    gw.patch(sites, json={"revision": held.get("revision", 1), "teamBackup": True},
             headers=priya)  # fmt: skip
    started, done = sign_in(gw, m["sign_in"], priya, at("test.fields-sites", sites_id), "priya.team", account="team")
    authorize = (fake.state()["authorize_requests"] or [{}])[-1]
    reached = call(gw, "fields_sites_get_record", {"id": "rec-1042"})
    check(
        "8 the sign-in address carries audience and prompt beside the platform's own state, client and redirect, the "
        f"lookup finds {SITE}, and the call reaches that site",
        sites_on.status_code == 200 and started.status_code == 200 and done.status_code == 200
        and authorize.get("audience") == "api.multi.test" and authorize.get("prompt") == "consent"
        and authorize.get("client_id") == "multi-app" and bool(authorize.get("state"))
        and output(reached).get("site") == SITE,
        {"started": started.text[:200], "done": done.text[:300], "authorize": authorize, "call": reached.text[:300]},
    )  # fmt: skip

    # 9. S4: James signs in with his own account, which reaches another site: refused, and no token kept for him.
    httpx.post(f"{m['control']}/site", json={"id": "site-other"}, verify=False, headers={"Host": "api.multi.test"})
    _, refused = sign_in(gw, m["sign_in"], james, at("test.fields-sites", sites_id), "james.person")
    mine = data(kept(gw.get("/v1/me/accounts", headers=james))) or []
    still = call(gw, "fields_sites_get_record", {"id": "rec-1042"})
    check(
        "9 James's own sign-in on another site is refused as signed in to another site, holds no token for him, and "
        "the team's calls still reach the team's site",
        refused.status_code == 400 and "another site" in refused.text
        and not any(r.get("connectionId") == sites_id and r.get("connected") for r in mine)
        and error(still).get("status") == 404,
        {"refused": refused.text[:300], "mine": mine, "still": still.text[:300]},
    )  # fmt: skip

    # 10. S4: a lookup naming a site that would change the address fails the team's sign-in and moves nothing; the
    # team admin's next sign-in replaces the site.
    httpx.post(f"{m['control']}/site", json={"id": "../admin?x=1"}, verify=False, headers={"Host": "api.multi.test"})
    _, bad = sign_in(gw, m["sign_in"], priya, at("test.fields-sites", sites_id), "priya.team", account="team")
    httpx.post(f"{m['control']}/site", json={"id": "site-other"}, verify=False, headers={"Host": "api.multi.test"})
    _, moved = sign_in(gw, m["sign_in"], priya, at("test.fields-sites", sites_id), "priya.team", account="team")
    now = call(gw, "fields_sites_get_record", {"id": "rec-1042"})
    check(
        "10 a lookup naming ../admin?x=1 fails the sign-in, and the team admin's own sign-in then moves the team to "
        "site-other",
        bad.status_code == 400 and moved.status_code == 200 and output(now).get("site") == "site-other",
        {"bad": bad.text[:300], "moved": moved.text[:300], "now": now.text[:300]},
    )  # fmt: skip

    leaked = [s for s in (SECRETS["token"], CLIENTS["multi-zoom"], CLIENTS["multi-app"]) if any(s in t for t in SEEN)]
    check("11 no answer in this run carried a token or a client secret", not leaked, leaked)


manifest = (SALESFORCE / "plugin.yaml").read_text() if (SALESFORCE / "plugin.yaml").exists() else ""
if "from_token" not in manifest:
    check(
        "12 the sign-in reads the instance from Salesforce's token answer, and query-all carries Sforce-Query-Options",
        False,
        f"{SALESFORCE} is a Salesforce plugin that does not read instance_url from the token answer; that is in "
        "chanl-ai/ops-ai-plugins#8: set OPS_SALESFORCE_PLUGIN to a checkout at or after it",
    )
    finish()

with ExitStack() as stack:
    sf = stack.enter_context(salesforce())
    api, _ = stack.enter_context(platform())
    plugins = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps([str(SALESFORCE)])}
    gw = stack.enter_context(
        tools({**sf["settings"], **AUTH, **plugins, "OPS_CONSOLE_URL": "https://console.acme.test"})
    )
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    priya_session = signed_in(api, "p.shah@harborpine.example")
    priya = bearer(priya_session, "team_ops")
    TENANT["id"] = str((priya_session.get("principal") or {}).get("tenantId") or priya_session.get("tenantId") or "")
    sfake = sf["fake"]
    for h in sf["hosts"]:
        gw.post("/v1/egress/hosts", json={"value": h, "note": "uc-584"}, headers=sam)
    gw.post("/v1/egress/ranges", json={"value": sf["range"], "note": "uc-584"}, headers=sam)
    # The org's company address, one of the places the Salesforce plugin signs in.
    login = sf["login_url"]
    team_on = {
        "signIn": "team",
        "settings": {"login_url": login},
        "credentialId": credential(gw, priya, "opsai.salesforce", "ops-ai-acme", "s3"),
    }
    turned = turn_on(gw, priya, "opsai.salesforce", **team_on)
    sf_id = str((data(turned) or {}).get("connectionId") or "con_missing")
    _, sf_done = sign_in(gw, sf["sign_in"], priya, at("opsai.salesforce", sf_id), "acme.integration")

    # 12. S4: Salesforce's instance comes from the token answer, with no UserInfo call, and query-all sends its batch
    # size.
    found = call(gw, "salesforce_find_cases_with_deleted", {"status": "Escalated"})
    state = sfake.state()
    check(
        "12 the sign-in reads the instance from Salesforce's token answer, and query-all carries Sforce-Query-Options",
        turned.status_code == 200 and sf_done.status_code == 200 and not state["userinfo"]
        and found.status_code == 200 and bool(output(found).get("records"))
        and state["query_options"][-1:] == ["batchSize=2000"],
        {"turned": turned.text[:200], "done": sf_done.text[:300], "userinfo": state["userinfo"],
         "call": found.text[:300], "options": state["query_options"]},
    )  # fmt: skip

finish()
