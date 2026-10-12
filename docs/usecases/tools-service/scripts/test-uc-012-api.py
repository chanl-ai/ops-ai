"""uc-012 a builder imports tools from OpenAPI and MCP and calls them, only on hosts the tenant allows, api layer:
docs/usecases/tools-service/import-tools.md."""

from __future__ import annotations

from typing import Any

import httpx
from fake_bank_https import HOST, fake_bank

from usecase_harness import check, data, finish, service_headers, tools

SECURITY = {"X-Dev-User": "Nadia Petrov"}


def clean(gw: httpx.Client, bank_range: str) -> None:
    """Leaves nothing from an earlier run on a kept database: its modules, the host and the range."""
    listed = data(gw.get("/v1/tool-modules", params={"search": "uc012", "pageSize": 50}))["data"]
    for m in listed:
        gw.delete(f"/v1/tool-modules/{m['id']}")
    gw.post("/v1/egress/hosts/remove", json={"value": HOST})
    gw.post("/v1/egress/ranges/remove", json={"value": bank_range})


def publish(gw: httpx.Client, module: dict[str, Any]) -> dict[str, Any]:
    reviewed = data(gw.post(f"/v1/tool-modules/{module['id']}/reviews", json={"note": "uc-012"}))
    review = reviewed["reviews"][0]["id"]
    return data(
        gw.post(
            f"/v1/tool-modules/{module['id']}/reviews/{review}/decide", json={"decision": "approved"}, headers=SECURITY
        )
    )


def create(gw: httpx.Client, name: str, source: dict[str, Any], operations: list[dict[str, Any]]) -> httpx.Response:
    body = {
        "name": name,
        "displayName": name,
        "system": name,
        "type": source["kind"],
        "endpoint": "",
        "connectionId": "int_core_banking",
        "operations": operations,
        "source": source,
    }
    return gw.post("/v1/tool-modules", json=body)


def call(gw: httpx.Client, tool: str, args: dict[str, Any]) -> httpx.Response:
    return gw.post(
        "/v1/calls",
        json={"tool": tool, "input": args, "key": tool, "runContext": {"act": "workflow:dispute_email"}},
        headers=service_headers("tools"),
    )


with fake_bank() as bank, tools(settings=bank.settings) as gw:
    clean(gw, bank.range)
    spec = {"kind": "openapi", "specUrl": f"https://{HOST}/v1/openapi.json"}
    unlisted = gw.post("/v1/tool-modules/discover", json=spec)
    check("a document on a host off the allow-list is refused (400)", unlisted.status_code == 400, unlisted.text[:200])
    gw.post("/v1/egress/hosts", json={"value": HOST, "note": "uc-012"})
    private = gw.post("/v1/tool-modules/discover", json=spec)
    check(
        "a listed host resolving to an unlisted private address is refused (400)",
        private.status_code == 400 and "may not reach" in private.text,
        private.text[:200],
    )
    check("nothing reached the bank while refused", not bank.received, bank.received)
    gw.post("/v1/egress/ranges", json={"value": bank.range, "note": "uc-012 fake bank"})
    found = gw.post("/v1/tool-modules/discover", json=spec)
    ops = {o["name"]: o["access"] for o in data(found).get("operations", [])} if found.status_code == 200 else {}
    check(
        "with the range listed, the document is read and every operation is a write",
        ops == {"get_account": "write", "latest_statement": "write"},
        found.text[:300],
    )

    forged = {
        "name": "get_account",
        "description": "",
        "access": "read",
        "method": "DELETE",
        "path": "/admin",
        "group": "x",
        "input": [],
    }
    made = create(gw, "uc012-statements", spec, [forged])
    module = data(made) if made.status_code == 201 else {}
    op = (module.get("operations") or [{}])[0]
    check(
        "create takes the operation from the document, not the caller",
        (op.get("method"), op.get("path")) == ("GET", "/accounts/{accountId}"),
        made.text[:300],
    )
    published = publish(gw, module)
    check("security approves the review and the module is published", published.get("status") == "published", published)
    ran = call(gw, "get_account", {"accountId": "CHQ-2219"})
    output = data(ran).get("output", {}) if ran.status_code == 200 else {}
    check(
        "the imported operation runs against the bank through the gateway",
        output.get("accountId") == "CHQ-2219",
        ran.text[:300],
    )

    mcp = {"kind": "mcp", "url": f"https://{HOST}/v1/mcp"}
    tools_found = gw.post("/v1/tool-modules/discover", json=mcp)
    check(
        "the MCP server's tools are discovered as writes",
        [(o["name"], o["access"]) for o in data(tools_found).get("operations", [])] == [("lookup_case", "write")],
        tools_found.text[:300],
    )
    case_desk = data(
        create(
            gw,
            "uc012-case-desk",
            mcp,
            [{"name": "lookup_case", "description": "", "access": "read", "group": "tools", "input": []}],
        )
    )
    publish(gw, case_desk)
    looked = call(gw, "lookup_case", {"caseId": "CASE-4112"})
    check(
        "an imported MCP tool runs through tools/call",
        data(looked).get("output", {}).get("tool") == "lookupCase",
        looked.text[:300],
    )
    bank.mcp_tools[0] = {**bank.mcp_tools[0], "name": "findCase"}
    renamed = {
        "source": mcp,
        "operations": [{"name": "find_case", "description": "", "access": "read", "group": "tools", "input": []}],
    }
    drifted = gw.post(f"/v1/tool-modules/{case_desk['id']}/operations/import", json=renamed)
    check(
        "the server dropping a reviewed tool marks the module drifted",
        data(drifted).get("drift") is True,
        drifted.text[:300],
    )
    stopped = call(gw, "find_case", {"caseId": "CASE-4112"})
    check(
        "a drifted module runs no calls (403)",
        stopped.status_code == 403 and "module_drifted" in stopped.text,
        stopped.text[:200],
    )
    clean(gw, bank.range)

finish()
