"""uc-611 a developer builds a REST tool and runs it for real, api layer:
docs/usecases/tools-service/a-developer-builds-a-rest-tool.md. tools-service with the core bank stand-in behind it: a
Real run of a form-encoded write from the tool page is logged under the person who sent it, and someone outside the
module's team cannot send one. No model call."""

from __future__ import annotations

import json
from contextlib import ExitStack

from connection_calls import SECURITY, allow_bank, clean, connection
from usecase_harness import AGENTS_PORT, TOOLS_PORT, agents, approve_tool_review, check, core_bank, data, finish, tools

EMAIL = "jo.reyes@example.com"
OUTSIDER = {"X-Dev-User": "Priya Shah", "X-Team-Id": "team_cards"}

with ExitStack() as stack:
    bank = stack.enter_context(core_bank())
    gw = stack.enter_context(tools({**bank["settings"], "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    base = f"https://{bank['host']}"
    clean(gw, "uc611")
    allow_bank(gw, bank)
    conn = connection(
        gw, "uc611 payments", "bearer", {"test": {"secretValues": {"token": "test-bearer-token"}}}, base_url=base
    )
    made = gw.post(
        "/v1/tool-modules",
        json={
            "name": "uc611-payments",
            "displayName": "uc611 payments",
            "system": "Payments stand-in",
            "type": "http",
            "endpoint": "",
            "connectionId": conn["id"],
            "http": {
                "name": "create_customer",
                "description": "Creates a customer with an email.",
                "access": "write",
                "method": "POST",
                "url": f"{base}/auth/bearer/customers",
                "bodyEncoding": "form",
                "body": json.dumps({"email": "{{email}}", "metadata[source]": "ops_ai"}),
            },
        },
    )
    check("1 the module is made (201)", made.status_code == 201, made.text[:300])
    mod = data(made)
    gw.post(f"/v1/tool-modules/{mod['id']}/reviews", json={"note": "uc-611"})
    published = approve_tool_review(gw, mod["id"], SECURITY)
    check("1 the module is published", published.get("status") == "published", published.get("status"))

    run = {"operation": "create_customer", "contextId": "owner", "target": "sandbox", "input": {"email": EMAIL}}
    sent = gw.post(f"/v1/tool-modules/{mod['id']}/test", json=run)
    out = data(sent)
    check(
        "9 James's Real run makes the customer",
        sent.status_code == 200 and out.get("stubbed") is False and str(out["output"].get("id", "")).startswith("cus_"),
        out,
    )
    rows = data(gw.get("/v1/executions", params={"tool": "create_customer", "pageSize": 20}))["data"]
    check(
        "9 the write is in the executions log under James, from the console, in test",
        [(r.get("channel"), r.get("environment")) for r in rows] == [("console", "test")],
        rows,
    )
    refused = gw.post(
        f"/v1/tool-modules/{mod['id']}/test", json={**run, "input": {"email": "x@example.com"}}, headers=OUTSIDER
    )
    again = data(gw.get("/v1/executions", params={"tool": "create_customer", "pageSize": 20}))["data"]
    check(
        "10 someone in Cards cannot run it for real, and nothing more is written",
        refused.status_code in (403, 404) and len(again) == 1,
        {"status": refused.status_code, "rows": len(again)},
    )

    # 11-13 (group F): the key and the base address come only from the connection.
    # 11. An operation addressed by its path alone runs against the connection's base address with its key.
    paths = gw.post(
        "/v1/tool-modules",
        json={
            "name": "uc611-by-path",
            "displayName": "uc611 by path",
            "system": "Payments stand-in",
            "type": "http",
            "connectionId": conn["id"],
            "http": {
                "name": "list_customers",
                "description": "Lists customers by email.",
                "access": "read",
                "method": "GET",
                "url": "/auth/bearer/customers/search?email={email}",
            },
        },
    )
    by_path = data(paths) or {}
    if paths.status_code == 201:
        # A Real run calls only a published module, so this one is reviewed and published first, as step 1's is.
        gw.post(f"/v1/tool-modules/{by_path['id']}/reviews", json={"note": "uc-611 by path"})
        approve_tool_review(gw, by_path["id"], SECURITY)
    read = (
        gw.post(
            f"/v1/tool-modules/{by_path.get('id')}/test",
            json={"operation": "list_customers", "contextId": "owner", "target": "sandbox", "input": {"email": EMAIL}},
        )
        if paths.status_code == 201
        else paths
    )
    check(
        "11 an operation addressed by its path alone reads from the connection's base address with its key",
        paths.status_code == 201 and read.status_code == 200 and EMAIL in read.text,
        ("target: waits on S4 and D3", paths.text[:200], read.text[:200]),
    )

    # 12. A module's own base address beside its connection is refused: there is one home for it.
    own = gw.post(
        "/v1/tool-modules",
        json={
            "name": "uc611-own-base",
            "displayName": "uc611 own base",
            "system": "Payments stand-in",
            "type": "http",
            "endpoint": "https://elsewhere.example",
            "connectionId": conn["id"],
            "http": {
                "name": "ping",
                "description": "Ping.",
                "access": "read",
                "method": "GET",
                "url": f"{base}/auth/bearer/customers",
            },
        },
    )
    check(
        "12 a module that names its own base address beside its connection is refused (400 or 422)",
        own.status_code in (400, 422),
        ("target: waits on D3", own.status_code, own.text[:200]),
    )

    # 13. A sign-in key in an operation's header is refused, typed or referenced: the connection signs every call.
    op = (mod.get("operations") or [{}])[0]
    literal = gw.patch(
        f"/v1/tool-modules/{mod['id']}/operations/{op.get('id')}",
        json={"headers": [{"key": "Authorization", "value": "Bearer sk_test_literal"}]},
    )
    referenced = gw.patch(
        f"/v1/tool-modules/{mod['id']}/operations/{op.get('id')}",
        json={"headers": [{"key": "Authorization", "value": "Bearer {{PAYMENTS_KEY}}"}]},
    )
    check(
        "13 a typed key in the Authorization header is refused (400)",
        literal.status_code == 400,
        (literal.status_code, literal.text[:200]),
    )
    check(
        "13 a secret referenced in the Authorization header is refused too, naming the connection",
        referenced.status_code == 400 and "connection" in referenced.text.lower(),
        ("target: waits on S4", referenced.status_code, referenced.text[:200]),
    )

finish()
