"""uc-390 a tool signs in with an API key from its app's account, in a header or the query, the sandbox account's in a
test run, api layer:
docs/usecases/tools-service/connections-api-key.md. tools-service with the core bank stand-in behind it; calls are sent
as agents-service sends them. No model call."""

from __future__ import annotations

from contextlib import ExitStack

from connection_calls import allow_bank, call, clean, connection, module
from usecase_harness import AGENTS_PORT, TOOLS_PORT, agents, check, core_bank, data, finish, tools

TEST_KEY, PROD_KEY = "test-bank-key", "prod-bank-key"

with ExitStack() as stack:
    bank = stack.enter_context(core_bank())
    gw = stack.enter_context(tools({**bank["settings"], "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    BANK_BASE = f"https://{bank['host']}"  # the stand-in's address, which its credentials are bound to
    clean(gw, "uc390")
    allow_bank(gw, bank)
    url = f"https://{bank['host']}/auth/api-key"

    # 1. A module with no connection sends no key: the bank refuses it.
    module(gw, "uc390-bare", url, None)
    bare = call(gw, "uc390_bare")
    check("1 with no connection the bank refuses the call (401)", bare.get("ok") is False, bare)

    # 2. An app with a live account and a sandbox account, each with its own key, sent as the X-Api-Key header.
    header = connection(
        gw,
        "uc390 header key",
        "api_key",
        {
            "sandbox": {"settings": {"name": "X-Api-Key"}, "secretValues": {"key": TEST_KEY}},
            "live": {"settings": {"name": "X-Api-Key"}, "secretValues": {"key": PROD_KEY}},
        },
        base_url=BANK_BASE,
    )
    shown = [data(gw.get(f"/v1/apps/{header['id']}/accounts/{a['id']}")) for a in (header, header["sandboxAccount"])]
    check(
        "2 each account says its key is set and never shows it",
        all(s["secrets"]["key"]["set"] for s in shown) and TEST_KEY not in str(shown) and PROD_KEY not in str(shown),
        shown,
    )
    made = module(gw, "uc390-header", url, header["id"])
    check("2 the module's operation carries no key header", made["operations"][0]["headers"] == [], made["operations"])
    test = call(gw, "uc390_header", environment="test")
    check(
        "2 a test call carries the sandbox account's key in the header",
        test.get("ok") and test["output"] == {"via": "header", "environment": "test"},
        test,
    )
    live = call(gw, "uc390_header", environment="live")
    check(
        "2 a live call carries the live account's key",
        live.get("ok") and live["output"] == {"via": "header", "environment": "production"},
        live,
    )
    unsaid = call(gw, "uc390_header")
    check(
        "2 a call that names no run is a test run, never the live account",
        unsaid.get("ok") and unsaid["output"]["environment"] == "test",
        unsaid,
    )

    # 3. The same kind sent in the query, on an app whose only account is a sandbox: a live call is refused, not sent
    # bare.
    query = connection(
        gw,
        "uc390 query key",
        "api_key",
        {"sandbox": {"settings": {"placement": "query", "name": "api_key"}, "secretValues": {"key": TEST_KEY}}},
        base_url=BANK_BASE,
    )
    module(gw, "uc390-query", url, query["id"])
    q = call(gw, "uc390_query", environment="test")
    check(
        "3 the key goes in the query when the account says so",
        q.get("ok") and q["output"] == {"via": "query", "environment": "test"},
        q,
    )
    unset = call(gw, "uc390_query", environment="live")
    check(
        "3 a live call on an app with only a sandbox account is refused as not set",
        unset.get("ok") is False and unset["output"]["error"]["code"] == "CONNECTION_NOT_SET",
        unset,
    )

    # 4. The call log keeps the run and the account, and no key.
    rows = data(gw.get("/v1/executions", params={"tool": "uc390_header", "pageSize": 20}))
    check("4 no key appears in the call log", TEST_KEY not in str(rows) and PROD_KEY not in str(rows), rows)
finish()
