"""uc-396 a builder adds an MCP server behind OAuth by its address: its sign-in found from the server, a client
registered, signed in once, its tools listed with their inputs, and called through the same executor, refreshed after
a 401, api layer: docs/usecases/tools-service/mcp-sign-in.md. The script plays the browser. No model call."""

from __future__ import annotations

import json
from contextlib import ExitStack
from urllib.parse import parse_qs, urlsplit

import httpx
from connection_calls import SECURITY, allow_bank, bank_control, call, clean
from usecase_harness import AGENTS_PORT, TOOLS_PORT, agents, approve_tool_review, check, core_bank, data, finish, tools

CONSOLE = "https://console.bank.test"

with ExitStack() as stack:
    bank = stack.enter_context(core_bank())
    settings = {**bank["settings"], "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}", "OPS_CONSOLE_URL": CONSOLE}
    gw = stack.enter_context(tools(settings))
    stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    clean(gw, "uc396")
    allow_bank(gw, bank)
    server = f"https://{bank['host']}/mcp/screening"
    address = json.loads(bank["settings"]["OPS_EGRESS_RESOLVE"])[bank["host"]]

    # 1. Listing the server's tools with no sign-in is refused, saying it needs sign-in.
    bare = gw.post("/v1/tool-modules/discover", json={"kind": "mcp", "url": server})
    check(
        "1 the server's tools are not listed before sign-in (sign_in_required)",
        bare.status_code == 400 and bare.json()["error"]["code"] == "sign_in_required",
        bare.text[:300],
    )

    # 2. Added by its address: the sign-in is found from the server and a client registered with it.
    made = gw.post("/v1/connections/mcp", json={"serverUrl": server, "name": "uc396 compliance screening"})
    check("2 the MCP connection is made (201)", made.status_code == 201, made.text[:300])
    conn = data(made) or {}
    env = conn.get("environments", {}).get("test", {}).get("settings", {})
    check(
        "2 it signs in with an account at the server's authorization server, for the server as its resource",
        conn.get("authKind") == "oauth2_auth_code"
        and env.get("authorizeUrl") == f"https://{bank['host']}/oauth2/authorize"
        and env.get("resource") == server
        and str(env.get("clientId", "")).startswith("dyn_"),
        env,
    )
    check("2 a client was registered once", bank_control(bank, "/oauth2/stats").get("registered") == 1, "registration")

    # 3. Someone who manages connections signs in once.
    path = f"/v1/connections/{conn.get('id')}"
    started = data(gw.post(f"{path}/sign-in", json={"environment": "test"})) or {}
    url = urlsplit(started.get("authorizeUrl", ""))
    asked = {k: v[0] for k, v in parse_qs(url.query).items()}
    check("3 the sign-in names the server as its resource", asked.get("resource") == server, asked)
    consent = httpx.get(f"https://{address}{url.path}?{url.query}", verify=False, follow_redirects=False)
    back = {k: v[0] for k, v in parse_qs(urlsplit(consent.headers.get("location", "")).query).items()}
    done = gw.post(f"{path}/sign-in/complete", json={"state": back.get("state", ""), "code": back.get("code", "")})
    check("3 the sign-in finishes (200)", done.status_code == 200, done.text[:300])

    # 4. With the connection, the tools are listed with their inputs.
    source = {"kind": "mcp", "url": server, "connectionId": conn.get("id")}
    found = gw.post("/v1/tool-modules/discover", json=source)
    ops = {o["name"]: [f["name"] for f in o["input"]] for o in (data(found) or {}).get("operations", [])}
    check(
        "4 the server's tools are listed with the inputs it declares",
        ops == {"check_sanctions": ["name", "country"], "get_sanctions_result": ["screeningId"]},
        found.text[:400],
    )
    chosen = [
        {"name": "check_sanctions", "description": "", "access": "read", "group": "tools", "input": []},
    ]
    body = {
        "name": "uc396-screening",
        "displayName": "uc396 screening",
        "system": "Compliance screening",
        "type": "mcp",
        "endpoint": "",
        "connectionId": conn.get("id"),
        "operations": chosen,
        "source": source,
    }
    module = gw.post("/v1/tool-modules", json=body)
    check("4 the module is created from the server's list (201)", module.status_code == 201, module.text[:300])
    m = data(module) or {}
    data(gw.post(f"/v1/tool-modules/{m.get('id')}/reviews", json={"note": "uc-396"}))
    published = approve_tool_review(gw, str(m.get("id")), SECURITY)
    check(
        "4 the operation keeps the server's input fields",
        [f["name"] for f in published["operations"][0]["input"]] == ["name", "country"],
        published["operations"],
    )

    # 5. An agent's or a workflow's call runs through the same executor, with the connection's token.
    first = call(gw, "check_sanctions", environment="test", key="s1", args={"name": "Ada Chen"})
    check(
        "5 the MCP tool runs with the signed-in client's token",
        first.get("ok")
        and first["output"]["tool"] == "checkSanctions"
        and first["output"]["client"].startswith("dyn_"),
        first,
    )
    bank_control(bank, "/oauth2/revoke-access", method="POST")
    again = call(gw, "check_sanctions", environment="test", key="s2", args={"name": "Ada Chen"})
    stats = bank_control(bank, "/oauth2/stats")
    check(
        "5 after the server refuses the token, one refresh for the same resource and the call succeeds",
        again.get("ok") is True and stats.get("refresh_token") == 1,
        (again, stats),
    )

    # 6. The bank's registered client is used as given, with no registration.
    given = gw.post(
        "/v1/connections/mcp",
        json={"serverUrl": server, "name": "uc396 registered", "clientId": "ops-console", "clientSecret": "ac-secret"},
    )
    test_settings = (data(given) or {}).get("environments", {}).get("test", {})
    check(
        "6 a registered client is used as given and its secret kept as a secret part",
        given.status_code == 201
        and test_settings.get("settings", {}).get("clientId") == "ops-console"
        and test_settings.get("secrets", {}).get("clientSecret", {}).get("set") is True
        and bank_control(bank, "/oauth2/stats").get("registered") == 1,
        given.text[:300],
    )
finish()
