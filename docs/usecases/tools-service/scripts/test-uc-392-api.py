"""uc-392 a tool signs in with a bearer token from its connection, by environment, api layer:
docs/usecases/tools-service/connections-bearer.md. tools-service with the core bank stand-in behind it.
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
    clean(gw, "uc392")
    allow_bank(gw, bank)
    conn = connection(
        gw,
        "uc392 bearer",
        "bearer",
        {
            "test": {"secretValues": {"token": "test-bearer-token"}},
            "production": {"secretValues": {"token": "prod-bearer-token"}},
        },
        base_url=BANK_BASE,
    )
    module(gw, "uc392-bearer", f"https://{bank['host']}/auth/bearer", conn["id"])
    test = call(gw, "uc392_bearer", environment="test")
    check("1 a test call carries the test token", test.get("ok") and test["output"] == {"environment": "test"}, test)
    live = call(gw, "uc392_bearer", environment="production")
    check(
        "1 a live call carries the production token",
        live.get("ok") and live["output"] == {"environment": "production"},
        live,
    )
    replaced = data(gw.get(f"/v1/connections/{conn['id']}"))
    res = gw.put(
        f"/v1/connections/{conn['id']}/environments/test",
        json={
            "revision": replaced["revision"],
            "settings": {"baseUrl": BANK_BASE},
            "secretValues": {"token": "not-the-token"},
        },
    )
    check("2 the test token is replaced (200)", res.status_code == 200, res.text[:200])
    after = call(gw, "uc392_bearer", environment="test", key="after-replace")
    check(
        "2 the next test call carries the new token, which the bank refuses",
        after.get("ok") is False and after["output"]["error"].get("status") == 401,
        after,
    )
    meta = data(gw.get("/v1/secrets"))
    owned = [s for s in meta if s.get("connectionId") == conn["id"]]
    check(
        "3 the Secrets list shows the token parts as the connection's, with no value",
        len(owned) == 2 and "not-the-token" not in str(meta) and "prod-bearer-token" not in str(meta),
        owned,
    )
    rotate = gw.post(f"/v1/secrets/{owned[0]['name']}/rotate", json={"value": "x"}) if owned else None
    check(
        "3 a connection's secret is not rotated on the Secrets page (409)",
        rotate is not None and rotate.status_code == 409,
        rotate.text[:200] if rotate is not None else None,
    )
finish()
