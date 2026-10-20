"""uc-394 a person signs a connection in once with the team's account (OAuth authorization code with PKCE), and tools
use and refresh its token, api layer: docs/usecases/tools-service/connections-sign-in.md. The script plays the browser:
it follows the sign-in address to the bank stand-in's authorize page and hands the code back as the console's return
page does. No model call."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from urllib.parse import parse_qs, urlsplit

import httpx
from connection_calls import allow_bank, bank_control, call, clean, connection, module
from usecase_harness import AGENTS_PORT, TOOLS_PORT, agents, check, core_bank, data, finish, tools

CONSOLE = "https://console.bank.test"
# Shorter than the minute before expiry when the gateway refreshes, so every call refreshes and spends the rotating
# refresh token: a refresh token not stored after rotation would fail the second call.
os.environ["FAKE_BANK_TOKEN_TTL"] = "30"

with ExitStack() as stack:
    bank = stack.enter_context(core_bank())
    settings = {**bank["settings"], "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}", "OPS_CONSOLE_URL": CONSOLE}
    gw = stack.enter_context(tools(settings))
    stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    BANK_BASE = f"https://{bank['host']}"  # the stand-in's address, which its credentials are bound to
    clean(gw, "uc394")
    allow_bank(gw, bank)
    base = f"https://{bank['host']}"
    address = json.loads(bank["settings"]["OPS_EGRESS_RESOLVE"])[bank["host"]]
    conn = connection(
        gw,
        "uc394 crm",
        "oauth2_auth_code",
        {
            "test": {
                "settings": {
                    "authorizeUrl": f"{base}/oauth2/authorize",
                    "tokenUrl": f"{base}/oauth2/token",
                    "clientId": "ops-console",
                    "scopes": "crm.read",
                },
                "secretValues": {"clientSecret": "ac-secret"},
            }
        },
        base_url=BANK_BASE,
    )
    module(gw, "uc394-read", f"{base}/auth/oauth", conn["id"])
    path = f"/v1/connections/{conn['id']}"

    # 1. Before anyone signs in, a call is refused, never sent without a token.
    before = call(gw, "uc394_read", environment="test", key="b1")
    check(
        "1 before sign-in the call is refused NOT_SIGNED_IN",
        before.get("ok") is False and before["output"]["error"]["code"] == "NOT_SIGNED_IN",
        before,
    )
    shown = data(gw.get(path))
    check(
        "1 the connection names the redirect address to register",
        shown["redirectUri"] == f"{CONSOLE}/connections/sign-in/return",
        shown["redirectUri"],
    )

    # 2. Sign-in starts: the browser goes to the system with a PKCE challenge, and comes back with a code and the state.
    started = gw.post(f"{path}/sign-in", json={"environment": "test"})
    check("2 sign-in starts (200)", started.status_code == 200, started.text[:300])
    url = urlsplit(data(started)["authorizeUrl"])
    asked = {k: v[0] for k, v in parse_qs(url.query).items()}
    check(
        "2 the sign-in address carries S256, the state and the console's return address",
        asked.get("code_challenge_method") == "S256" and asked.get("redirect_uri", "").startswith(CONSOLE),
        asked,
    )
    consent = httpx.get(f"https://{address}{url.path}?{url.query}", verify=False, follow_redirects=False)
    back = {k: v[0] for k, v in parse_qs(urlsplit(consent.headers.get("location", "")).query).items()}
    check("2 the system sends the browser back with a code", consent.status_code == 302 and "code" in back, back)

    # 3. Only the person who started finishes it, once.
    finish_body = {"state": back.get("state", ""), "code": back.get("code", "")}
    stolen = gw.post(f"{path}/sign-in/complete", json=finish_body, headers={"X-Dev-User": "Maya Okafor"})
    check(
        "3 another person cannot finish the sign-in (sign_in_expired)",
        stolen.status_code == 400 and stolen.json()["error"]["code"] == "sign_in_expired",
        stolen.text[:300],
    )
    done = gw.post(f"{path}/sign-in/complete", json=finish_body)
    signed = (data(done) or {}).get("environments", {}).get("test", {}).get("signedIn") or {}
    check("3 the person who started finishes it (200)", done.status_code == 200, done.text[:300])
    check("3 the connection says which account signed in", signed.get("account") == "svc-lending@bank.test", signed)
    check("3 no token is shown", "at_" not in done.text and "rt_" not in done.text, "token in the detail")
    replay = gw.post(f"{path}/sign-in/complete", json=finish_body)
    check(
        "3 the same state again is refused (sign_in_expired)",
        replay.status_code == 400 and replay.json()["error"]["code"] == "sign_in_expired",
        replay.text[:300],
    )

    # 4. Tools use the account's token; each refresh spends the rotated refresh token, and the next one still works.
    first, second = (
        call(gw, "uc394_read", environment="test", key="c1"),
        call(gw, "uc394_read", environment="test", key="c2"),
    )
    stats = bank_control(bank, "/oauth2/stats")
    check(
        "4 both calls run on the signed-in account's token",
        first.get("ok") and second.get("ok") and first["output"]["client"] == "ops-console",
        (first, second),
    )
    check("4 each call refreshed the token and both refreshes were accepted", stats["refresh_token"] == 2, stats)

    # 5. Signing out stops tools at once.
    out = gw.post(f"{path}/sign-out", json={"environment": "test"})
    after = call(gw, "uc394_read", environment="test", key="c3")
    check(
        "5 after sign-out the call is refused NOT_SIGNED_IN",
        out.status_code == 200 and after.get("ok") is False and after["output"]["error"]["code"] == "NOT_SIGNED_IN",
        (out.text[:200], after),
    )
    activity = [a["action"] for a in data(gw.get(path))["activity"]]
    check("5 the activity records the sign-in and the sign-out", {"signed_in", "signed_out"} <= set(activity), activity)
finish()
