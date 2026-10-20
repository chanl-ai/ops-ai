"""uc-391 a tool signs in with a username and password from its connection, by environment, api layer:
docs/usecases/tools-service/connections-basic.md. tools-service with the core bank stand-in behind it.
No model call."""

from __future__ import annotations

from contextlib import ExitStack

from connection_calls import allow_bank, call, clean, connection, module
from usecase_harness import AGENTS_PORT, TOOLS_PORT, agents, check, core_bank, data, finish, tools

with ExitStack() as stack:
    bank = stack.enter_context(core_bank())
    gw = stack.enter_context(tools({**bank["settings"], "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    BANK_BASE = f"https://{bank['host']}"  # the stand-in's address, which its credentials are bound to
    clean(gw, "uc391")
    allow_bank(gw, bank)
    conn = connection(
        gw,
        "uc391 basic",
        "basic",
        {
            "test": {"settings": {"username": "ops-test"}, "secretValues": {"password": "test-pass"}},
            "production": {"settings": {"username": "ops-prod"}, "secretValues": {"password": "prod-pass"}},
        },
        base_url=BANK_BASE,
    )
    shown = data(gw.get(f"/v1/connections/{conn['id']}"))
    check(
        "1 the username shows, the password is set and never shown",
        shown["environments"]["test"]["settings"].get("username") == "ops-test"
        and shown["environments"]["test"]["secrets"]["password"]["set"]
        and "test-pass" not in str(shown),
        shown["environments"]["test"],
    )
    module(gw, "uc391-basic", f"https://{bank['host']}/auth/basic", conn["id"])
    test = call(gw, "uc391_basic", environment="test")
    check(
        "2 a test call signs in as the test user",
        test.get("ok") and test["output"] == {"user": "ops-test", "environment": "test"},
        test,
    )
    live = call(gw, "uc391_basic", environment="production")
    check(
        "2 a live call signs in as the production user",
        live.get("ok") and live["output"] == {"user": "ops-prod", "environment": "production"},
        live,
    )
    wrong = gw.put(
        f"/v1/connections/{conn['id']}/environments/test",
        json={"revision": 1, "settings": {"username": "ops-test", "baseUrl": BANK_BASE}},
    )
    check("3 a change against an old revision is refused (409)", wrong.status_code == 409, wrong.text[:200])
    secret_in_settings = gw.put(
        f"/v1/connections/{conn['id']}/environments/test",
        json={
            "revision": shown["revision"],
            "settings": {"username": "ops-test", "password": "x", "baseUrl": BANK_BASE},
        },
    )
    check(
        "3 a secret part sent as a plain setting is refused (400)",
        secret_in_settings.status_code == 400,
        secret_in_settings.text[:200],
    )
    rows = data(gw.get("/v1/executions", params={"tool": "uc391_basic", "pageSize": 20}))
    check(
        "4 each call row names its environment and connection, and no password",
        sorted(r.get("environment") for r in rows["data"]) == ["production", "test"]
        and all(r.get("connectionId") == conn["id"] for r in rows["data"])
        and "test-pass" not in str(rows)
        and "prod-pass" not in str(rows),
        rows["data"],
    )
finish()
