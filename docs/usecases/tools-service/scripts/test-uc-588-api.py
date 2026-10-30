"""uc-588, api layer: docs/usecases/tools-service/plugin-sign-in-methods.md, stories S1 to S5.

platform-service signs the seeded people in and holds the install switch (the `plugins` policy); tools-service runs
with plugins on and loads one test plugin per sign-in method from services/tools-service/tests/plugin_kinds
(OPS_PLUGIN_PATHS); the fake system (docs/usecases/lib/fake_multi_auth.py) accepts each method's credential only,
issues OAuth tokens through mock-oauth2-server, and serves a listener that demands a client certificate. No model
call."""

from __future__ import annotations

import json
from contextlib import ExitStack
from typing import Any
from uuid import uuid4

import httpx
from fake_multi_auth import CLIENTS, SECRETS, digest, multi_auth
from usecase_harness import (
    LOG_DIR,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    TOOLS_PORT,
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

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
KINDS = REPO / "services/tools-service/tests/plugin_kinds"
FOLDERS = sorted(str(p) for p in KINDS.glob("kinds_*"))
PLUGINS = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps(FOLDERS)}
STATIC = {
    "test.open": ("open", {}),
    "test.header-key": ("header_key", {"key": SECRETS["key"]}),
    "test.query-key": ("query_key", {"key": SECRETS["key"]}),
    "test.basic": ("basic", {"username": SECRETS["username"], "password": SECRETS["password"]}),
    "test.bearer": ("bearer", {"token": SECRETS["token"]}),
}
WRONG = "wrong-secret-0000"
TENANT: dict[str, str] = {}
# Every answer the use case reads, searched at the end for any secret it gave.
SEEN: list[str] = []


def kept(r: httpx.Response) -> httpx.Response:
    SEEN.append(r.text)
    return r


def call(gw: httpx.Client, tool: str, team: str = "team_ops", args: dict[str, Any] | None = None) -> httpx.Response:
    """A gateway call as agents-service makes it for a run in `team` with nobody behind it: a read, runs at once."""
    headers = service_headers("tools", tenant=TENANT["id"], service="agents", team=team)
    body = {"tool": tool, "input": args or {}, "key": uuid4().hex, "runContext": {"environment": "production"}}
    return kept(gw.post("/v1/calls", json=body, headers=headers | {"X-Team-Id": team}))


def output(r: httpx.Response) -> dict[str, Any]:
    return dict((data(r) or {}).get("output") or {}) if r.status_code == 200 else {}


def error(r: httpx.Response) -> dict[str, Any]:
    try:
        body = r.json()
    except ValueError:
        return {}
    found = (body.get("data") or {}).get("output", {}).get("error") if body.get("data") else body.get("error")
    return dict(found or {})


def turn_on(gw: httpx.Client, who: dict[str, str], plugin: str, **body: Any) -> httpx.Response:
    return kept(gw.put(f"/v1/plugins/{plugin}/team", json={"enabled": True, **body}, headers=who))


def health(gw: httpx.Client, who: dict[str, str], connection_id: str, account: str = "self") -> dict[str, Any]:
    r = kept(
        gw.post(
            f"/v1/connections/{connection_id}/test",
            json={"environment": "production", "account": account},
            headers=who,
        )
    )
    return dict((data(r) or {}).get("health") or {"status": f"http {r.status_code}", "text": r.text[:200]})


def last(fake: Any, method: str) -> dict[str, Any]:
    return next((c for c in reversed(fake.state()["calls"]) if c["method"] == method), {})


def sign_in_own(gw: httpx.Client, m: dict[str, Any], who: dict[str, str], connection_id: str, user: str) -> int:
    started = gw.post(f"/v1/connections/{connection_id}/sign-in", json={"environment": "production"}, headers=who)
    back = m["sign_in"]((data(started) or {}).get("authorizeUrl", ""), user) if started.status_code == 200 else {}
    done = gw.post(
        f"/v1/connections/{connection_id}/sign-in/complete",
        json={"state": back.get("state", ""), "code": back.get("code", "")},
        headers=who,
    )
    if done.status_code != 200:
        print(f"sign-in for {user}: start {started.status_code} {started.text[:200]}; done {done.text[:200]}")
    return done.status_code


with ExitStack() as stack:
    m = stack.enter_context(multi_auth())
    fake = m["fake"]
    api, _ = stack.enter_context(platform())
    gw = stack.enter_context(
        tools({**m["settings"], **AUTH, **PLUGINS, "OPS_CONSOLE_URL": "https://console.acme.test"})
    )
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    priya_session = signed_in(api, "p.shah@harborpine.example")
    priya = bearer(priya_session, "team_ops")
    TENANT["id"] = str((priya_session.get("principal") or {}).get("tenantId") or priya_session.get("tenantId") or "")
    james = bearer(signed_in(api, "j.richardson@harborpine.example"), "team_ops")
    maya = bearer(signed_in(api, "m.okafor@harborpine.example"), "team_ops")
    wanjiru = bearer(signed_in(api, "w.kamau@harborpine.example"), "team_platform")

    # 1. The platform admin turns every test plugin on for the install; Security lists the system's hosts.
    loaded = data(gw.get("/v1/plugins", headers=priya)) or {}
    ids = sorted(p["id"] for p in loaded.get("plugins", []))
    policy = api.put("/v1/policies/plugins", json={"value": {i: {"enabled": True} for i in ids}}, headers=sam)
    # The install switch is read through a short cache; every plugin reads as on before a team turns one on.
    until(
        lambda: all(p["installOn"] for p in (data(gw.get("/v1/plugins", headers=priya)) or {}).get("plugins", [])),
        timeout=30,
    )
    allowed = [gw.post("/v1/egress/hosts", json={"value": h, "note": "uc-588"}, headers=sam) for h in m["hosts"]]
    allowed.append(gw.post("/v1/egress/ranges", json={"value": m["range"], "note": "uc-588"}, headers=sam))
    check(
        "1 all eight test plugins load, the platform admin turns them on, and Security lists the system's hosts",
        len(ids) == 8 and not loaded.get("failed") and policy.status_code == 200
        and all(r.status_code in (200, 201, 409) for r in allowed),
        {"ids": ids, "failed": loaded.get("failed"), "policy": policy.text[:200]},
    )  # fmt: skip

    # 2-6. Each method a team gives once: turned on, Test connection passes, and a run's call reaches the system
    # signed in the way the plugin said.
    for n, (plugin, (short, credentials)) in enumerate(STATIC.items(), start=2):
        on = turn_on(gw, priya, plugin, credentials=credentials)
        connection_id = str((data(on) or {}).get("connectionId") or "con_missing")
        tested = health(gw, priya, connection_id)
        method = plugin.removeprefix("test.")
        called = call(gw, f"{short}_get_record", args={"id": "rec-1042"})
        seen = last(fake, method)
        secret = next(iter(v for k, v in credentials.items() if k != "username"), None)
        check(
            f"{n} {method}: turned on with its credential, Test connection passes, and the call reaches the system "
            "signed in where the plugin said",
            on.status_code == 200 and tested.get("status") == "ok"
            and output(called).get("record", {}).get("id") == "rec-1042"
            and seen.get("accepted") is True and seen.get("credential") == (digest(secret) if secret else None),
            {"on": on.text[:200], "health": tested, "call": called.text[:300], "seen": seen},
        )  # fmt: skip

    # 7. OAuth client credentials: the token comes from the plugin's token address; after it expires, a new one.
    cc_on = turn_on(gw, priya, "test.client", clientId="multi-cc", clientSecret=CLIENTS["multi-cc"])
    cc_id = str((data(cc_on) or {}).get("connectionId") or "con_missing")
    cc_health = health(gw, priya, cc_id)
    first = call(gw, "client_get_record", args={"id": "rec-1042"})
    fake.expire()
    renewed = call(gw, "client_get_record", args={"id": "rec-1042"})
    grants = [r["grant"] for r in fake.state()["token_requests"] if r["client"] == "multi-cc" and r["accepted"]]
    check(
        "7 a client-credentials plugin fetches its token, and after the token expires the next call gets a new one",
        cc_on.status_code == 200 and cc_health.get("status") == "ok"
        and output(first).get("as") == "client" and output(renewed).get("as") == "client"
        and grants.count("client_credentials") >= 2,
        {"on": cc_on.text[:200], "health": cc_health, "renewed": renewed.text[:300], "grants": grants},
    )  # fmt: skip

    # 8. Each person signs in with their own account; Test connection as each reaches the system as that person; a
    # call with nobody behind it gets no one's account.
    person_on = turn_on(
        gw, priya, "test.person", signIn="person", clientId="multi-app", clientSecret=CLIENTS["multi-app"]
    )
    person_id = str((data(person_on) or {}).get("connectionId") or "con_missing")
    signed = [sign_in_own(gw, m, james, person_id, "james.person"), sign_in_own(gw, m, maya, person_id, "maya.person")]
    as_james = health(gw, james, person_id)
    james_seen = last(fake, "person").get("as")
    as_maya = health(gw, maya, person_id)
    maya_seen = last(fake, "person").get("as")
    nobody = call(gw, "person_get_record", args={"id": "rec-1042"})
    check(
        "8 two people sign in with their own accounts, each one's test reaches the system as them, and a call with "
        "nobody behind it is refused with CONNECTION_NOT_LINKED",
        person_on.status_code == 200 and signed == [200, 200]
        and as_james.get("status") == "ok" and james_seen == "james.person"
        and as_maya.get("status") == "ok" and maya_seen == "maya.person"
        and error(nobody).get("code") == "CONNECTION_NOT_LINKED",
        {"on": person_on.text[:200], "signed": signed, "james": (as_james, james_seen),
         "maya": (as_maya, maya_seen), "nobody": nobody.text[:300]},
    )  # fmt: skip

    # 9. A person's token is renewed with its refresh token once it expires.
    fake.expire()
    again = health(gw, james, person_id)
    refreshed = [r for r in fake.state()["token_requests"] if r["grant"] == "refresh_token" and r["accepted"]]
    check(
        "9 after James's token expires, his next use renews it with the refresh token and still acts as James",
        again.get("status") == "ok" and last(fake, "person").get("as") == "james.person" and len(refreshed) >= 1,
        {"health": again, "refreshes": len(refreshed)},
    )

    # 10. A client certificate given beside the sign-in is presented on Test connection and the call.
    cert = {"clientCertificate": m["client_cert"], "clientKey": m["client_key"], "trustedCa": m["mtls_ca"]}
    cert_on = turn_on(gw, priya, "test.cert", settings={"base_url": m["mtls_base"]}, credentials=cert)
    cert_id = str((data(cert_on) or {}).get("connectionId") or "con_missing")
    cert_health = health(gw, priya, cert_id)
    cert_call = call(gw, "cert_get_record", args={"id": "rec-1042"})
    check(
        "10 a team gives a client certificate, its key and the system's CA; Test connection and the call pass",
        cert_on.status_code == 200 and cert_health.get("status") == "ok"
        and output(cert_call).get("as") == "certificate",
        {"on": cert_on.text[:200], "health": cert_health, "call": cert_call.text[:300]},
    )  # fmt: skip

    # 11. Wrong secrets, in a second team: a wrong key fails Test connection naming the 401 and the call with
    # UPSTREAM_ERROR 401; a wrong client secret fails at the token fetch and the connection needs reconnecting; no
    # certificate fails as a TLS handshake failure.
    bad_key = turn_on(gw, wanjiru, "test.header-key", credentials={"key": WRONG})
    bad_key_id = str((data(bad_key) or {}).get("connectionId") or "con_missing")
    bad_key_health = health(gw, wanjiru, bad_key_id)
    bad_key_call = call(gw, "header_key_get_record", team="team_platform", args={"id": "rec-1042"})
    bad_cc = turn_on(gw, wanjiru, "test.client", clientId="multi-cc", clientSecret=WRONG)
    bad_cc_id = str((data(bad_cc) or {}).get("connectionId") or "con_missing")
    bad_cc_call = call(gw, "client_get_record", team="team_platform", args={"id": "rec-1042"})
    bad_cc_status = (data(kept(gw.get(f"/v1/connections/{bad_cc_id}", headers=wanjiru))) or {}).get("status")
    only_ca = {"trustedCa": m["mtls_ca"]}
    no_cert = turn_on(gw, wanjiru, "test.cert", settings={"base_url": m["mtls_base"]}, credentials=only_ca)
    no_cert_id = str((data(no_cert) or {}).get("connectionId") or "con_missing")
    no_cert_health = health(gw, wanjiru, no_cert_id)
    no_cert_call = call(gw, "cert_get_record", team="team_platform", args={"id": "rec-1042"})
    check(
        "11 a wrong key fails with the system's 401, a wrong client secret with AUTH_FAILED and needs_reconnect, and "
        "a missing certificate with TLS_FAILED, on Test connection and the call",
        bad_key_health.get("status") == "failed" and "401" in str(bad_key_health.get("message"))
        and error(bad_key_call).get("code") == "UPSTREAM_ERROR" and error(bad_key_call).get("status") == 401
        and error(bad_cc_call).get("code") == "AUTH_FAILED" and bad_cc_status == "needs_reconnect"
        and no_cert_health.get("code") == "TLS_FAILED" and error(no_cert_call).get("code") == "TLS_FAILED",
        {"key": (bad_key_health, error(bad_key_call)), "cc": (error(bad_cc_call), bad_cc_status),
         "cert": (no_cert_health, error(no_cert_call))},
    )  # fmt: skip

    # 12. A Python tool that returns what the system says it was sent never carries the token.
    echoed = call(gw, "bearer_echo")
    check(
        "12 a plugin's Python tool that echoes the request it sent returns no credential",
        echoed.status_code == 200 and bool(output(echoed)) and SECRETS["token"] not in echoed.text,
        echoed.text[:300],
    )

    # 13. No answer read above, no call log row and no service log line carries any secret given.
    for who in (priya, wanjiru):
        SEEN.append(gw.get("/v1/plugins", headers=who).text)
        SEEN.append(gw.get("/v1/connections", headers=who).text)
        SEEN.append(gw.get("/v1/executions", headers=who).text)
    logs = "".join(p.read_text(errors="replace") for p in LOG_DIR.glob(f"tools-{TOOLS_PORT}.log"))
    secrets = [*SECRETS.values(), *CLIENTS.values(), WRONG, m["client_key"].split("\n")[1]]
    leaked = [digest(s) for s in secrets if s != SECRETS["username"] and any(s in t for t in [*SEEN, logs])]
    check(
        "13 no API answer, call log row or tools-service log line shows a key, password, token, client secret or "
        "private key",
        not leaked and len(SEEN) > 20 and bool(logs),
        {"leaked (digests)": leaked, "answers read": len(SEEN)},
    )

finish()
