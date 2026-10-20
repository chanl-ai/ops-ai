"""uc-393 a tool signs in with an OAuth client ID and secret: one token fetched, reused, fetched again after a 401 on a
read, never resent on a write, api layer: docs/usecases/tools-service/connections-client-credentials.md.
tools-service with the core bank stand-in, which is also the OAuth server. No model call."""

from __future__ import annotations

from contextlib import ExitStack

from connection_calls import allow_bank, bank_control, call, clean, connection, module
from usecase_harness import AGENTS_PORT, TOOLS_PORT, agents, check, core_bank, data, finish, tools

with ExitStack() as stack:
    bank = stack.enter_context(core_bank())
    gw = stack.enter_context(tools({**bank["settings"], "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    BANK_BASE = f"https://{bank['host']}"  # the stand-in's address, which its credentials are bound to
    clean(gw, "uc393")
    allow_bank(gw, bank)
    base = f"https://{bank['host']}"
    settings = {"tokenUrl": f"{base}/oauth2/token", "clientId": "ops-gateway", "scopes": "accounts.read"}
    conn = connection(
        gw,
        "uc393 card network",
        "oauth2_client_credentials",
        {"test": {"settings": settings, "secretValues": {"clientSecret": "cc-secret"}}},
        base_url=BANK_BASE,
    )
    module(gw, "uc393-read", f"{base}/auth/oauth", conn["id"])
    module(gw, "uc393-hold", f"{base}/auth/oauth/holds", conn["id"], access="write", method="POST", at_once=True)

    # 1. Two reads: one token, fetched with the client's secret through the egress client, reused for the second.
    first, second = (
        call(gw, "uc393_read", environment="test", key="r1"),
        call(gw, "uc393_read", environment="test", key="r2"),
    )
    stats = bank_control(bank, "/oauth2/stats")
    check(
        "1 both reads carry a client-credentials token",
        first.get("ok") and second.get("ok") and first["output"]["grant"] == "client_credentials",
        (first, second),
    )
    check("1 the second read reuses the first token: one token issued", stats["client_credentials"] == 1, stats)
    shown = data(gw.get(f"/v1/connections/{conn['id']}"))
    check(
        "1 the connection shows the token's time and permissions, never the token",
        shown["environments"]["test"]["signedIn"]["scopes"] == ["accounts.read"] and "at_" not in str(shown),
        shown["environments"]["test"]["signedIn"],
    )

    # 2. The system stops honouring the token: a read is answered 401, the gateway gets a new token and asks once more.
    bank_control(bank, "/oauth2/revoke-access", method="POST")
    again = call(gw, "uc393_read", environment="test", key="r3")
    stats = bank_control(bank, "/oauth2/stats")
    check("2 the read after a 401 succeeds on a new token", again.get("ok") is True, again)
    check("2 exactly one more token was fetched", stats["client_credentials"] == 2, stats)

    # 3. A write refused with 401 is not sent twice: it fails AUTH_EXPIRED on our side, and the bank saw it once.
    hold = call(gw, "uc393_hold", environment="test", key="w1")
    check("3 a write runs on the held token", hold.get("ok") is True, hold)
    bank_control(bank, "/oauth2/revoke-access", method="POST")
    holds_before = bank_control(bank, "/oauth2/stats")["holds"]
    refused = call(gw, "uc393_hold", environment="test", key="w2")
    holds_after = bank_control(bank, "/oauth2/stats")["holds"]
    check(
        "3 a write refused with 401 fails AUTH_EXPIRED and is not resent",
        refused.get("ok") is False
        and refused["output"]["error"]["code"] == "AUTH_EXPIRED"
        and holds_after - holds_before == 1,
        (refused, holds_before, holds_after),
    )

    # 4. A secret the system refuses marks the connection as needing attention, saying what it refused.
    wrong = connection(
        gw,
        "uc393 wrong secret",
        "oauth2_client_credentials",
        {"test": {"settings": settings, "secretValues": {"clientSecret": "not-the-secret"}}},
        base_url=BANK_BASE,
    )
    module(gw, "uc393-wrong", f"{base}/auth/oauth", wrong["id"])
    failed = call(gw, "uc393_wrong", environment="test")
    after = data(gw.get(f"/v1/connections/{wrong['id']}"))
    check(
        "4 a refused secret fails the call AUTH_FAILED on the system's side",
        failed.get("ok") is False
        and failed["output"]["error"]["code"] == "AUTH_FAILED"
        and failed["output"]["error"]["side"] == "upstream",
        failed,
    )
    check(
        "4 the connection needs attention, says why, and its activity records it",
        after["status"] == "needs_reconnect"
        and "invalid_client" in (after["statusDetail"] or "")
        and any(a["action"] == "refresh_failed" for a in after["activity"]),
        (after["status"], after["statusDetail"], after["activity"][:2]),
    )

    # 5. A token address off the allow-list is never reached.
    off = connection(
        gw,
        "uc393 unlisted",
        "oauth2_client_credentials",
        {
            "test": {
                "settings": {**settings, "tokenUrl": "https://login.unlisted.test/token"},
                "secretValues": {"clientSecret": "cc-secret"},
            }
        },
        base_url=BANK_BASE,
    )
    module(gw, "uc393-unlisted", f"{base}/auth/oauth", off["id"])
    denied = call(gw, "uc393_unlisted", environment="test")
    check(
        "5 a token address off the allow-list is refused EGRESS_DENIED",
        denied.get("ok") is False and denied["output"]["error"]["code"] == "EGRESS_DENIED",
        denied,
    )
    rows = data(gw.get("/v1/executions", params={"pageSize": 50}))
    check("6 no client secret appears in the call log", "cc-secret" not in str(rows), "secret found")
finish()
