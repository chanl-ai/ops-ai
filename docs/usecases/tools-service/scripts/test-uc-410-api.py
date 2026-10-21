"""uc-410 an assistant lists and runs a team's read tools over MCP with an API key, api layer:
docs/usecases/tools-service/mcp-server.md. platform-service issues the keys and signs people in; tools-service and
agents-service verify its tokens; the core bank stand-in answers the calls. The client is the official MCP Python SDK.
No model call."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from typing import Any

import httpx
import httpx2
from connection_calls import allow_bank, clean, connection, module
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import Implementation
from usecase_harness import (
    AGENTS_PORT,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    TOOLS_PORT,
    agents,
    bearer,
    check,
    core_bank,
    data,
    finish,
    platform,
    signed_in,
    tools,
)

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
MCP = f"http://127.0.0.1:{TOOLS_PORT}/mcp"
CLIENT = "uc-410 assistant"
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
ACCEPT = {"Accept": "application/json, text/event-stream"}


def session(credential: str) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(headers={"Authorization": f"Bearer {credential}"}, timeout=30)


async def listed(credential: str, path: str) -> dict[str, Any]:
    async with (
        session(credential) as http,
        Client(
            streamable_http_client(f"{MCP}{path}", http_client=http),
            client_info=Implementation(name=CLIENT, version="1.0"),
            cache=None,
        ) as c,
    ):
        return {t.name: t for t in (await c.list_tools()).tools}


async def called(credential: str, path: str, tool: str, args: dict[str, Any]) -> Any:
    async with (
        session(credential) as http,
        Client(
            streamable_http_client(f"{MCP}{path}", http_client=http),
            client_info=Implementation(name=CLIENT, version="1.0"),
            cache=None,
        ) as c,
    ):
        return await c.call_tool(tool, args)


def refused(credential: str | None, path: str) -> tuple[int, str]:
    headers = ACCEPT | ({"Authorization": f"Bearer {credential}"} if credential else {})
    r = httpx.post(f"{MCP}{path}", json=LIST, headers=headers, timeout=30)
    code = (
        r.json().get("error", {}).get("code", "")
        if r.headers.get("content-type", "").startswith("application/json")
        else ""
    )
    return r.status_code, code


with ExitStack() as stack:
    api, _ = stack.enter_context(platform())
    bank = stack.enter_context(core_bank())
    gw_url = f"http://127.0.0.1:{TOOLS_PORT}"
    stack.enter_context(tools({**bank["settings"], **AUTH, "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    stack.enter_context(agents(gateway_url=gw_url, env=AUTH))

    priya = signed_in(api, "p.shah@harborpine.example")
    sam = signed_in(api, "s.adeyemi@harborpine.example")
    nadia = signed_in(api, "n.petrov@harborpine.example")
    wanjiru = signed_in(api, "w.kamau@harborpine.example")
    ravi = signed_in(api, "r.menon@harborpine.example")
    ops = stack.enter_context(httpx.Client(base_url=gw_url, headers=bearer(priya, "team_ops"), timeout=30))
    security = stack.enter_context(httpx.Client(base_url=gw_url, headers=bearer(sam, "team_security"), timeout=30))

    # Setup: Priya (team_ops admin) connects the bank and publishes a read and a write declared to run at once.
    clean(ops, "uc410")
    allow_bank(security, bank)
    key = {"settings": {"name": "X-Api-Key"}, "secretValues": {"key": "dev-bank-key"}}
    conn = connection(ops, "uc410 core banking", "api_key", {"test": key}, base_url=f"https://{bank['host']}")
    approver = bearer(nadia, "team_security")
    base = f"https://{bank['host']}/accounts/{{account_id}}"
    module(ops, "uc410-get-account", base, conn["id"], security=approver)
    module(
        ops,
        "uc410-place-hold",
        f"{base}/holds",
        conn["id"],
        access="write",
        method="POST",
        at_once=True,
        security=approver,
    )
    ops_key = data(
        api.post("/v1/api-keys", headers=bearer(priya, "team_ops"), json={"name": "uc410", "scopes": ["read"]})
    )
    fraud_key = data(
        api.post("/v1/api-keys", headers=bearer(wanjiru, "team_fraud"), json={"name": "uc410", "scopes": ["read"]})
    )
    OPS_KEY, FRAUD_KEY = ops_key["secret"], fraud_key["secret"]

    # 1. A team_ops key lists the team's reads, with schemas and readOnlyHint, and no writes.
    tools_seen = asyncio.run(listed(OPS_KEY, "/test/team_ops"))
    read = tools_seen.get("uc410_get_account")
    check(
        "1 the key lists the team's read with its input schema and readOnlyHint",
        read is not None
        and "account_id" in read.input_schema.get("properties", {})
        and bool(read.annotations and read.annotations.read_only_hint),
        sorted(tools_seen),
    )
    check("1 the write is not listed", "uc410_place_hold" not in tools_seen, sorted(tools_seen))

    # 2. A read runs through the gateway against the bank, and the log names mcp, the key and the client.
    result = asyncio.run(called(OPS_KEY, "/test/team_ops", "uc410_get_account", {"account_id": "CHQ-2219"}))
    out = result.structured_content or {}
    check(
        "2 the read answers with the bank's own account",
        result.is_error is False and out.get("id") == "CHQ-2219" and out.get("holds") == [],
        result,
    )
    rows = data(ops.get("/v1/executions", params={"tool": "uc410_get_account", "pageSize": 5}))["data"]
    check(
        "2 the call log row names channel mcp, the client and test",
        bool(rows)
        and rows[0].get("channel") == "mcp"
        and rows[0].get("clientName") == CLIENT
        and rows[0].get("environment") == "test"
        and rows[0]["status"] == "ok",
        rows[:1],
    )

    # 3. A write called by name is refused by the gateway, logged, and the bank keeps no hold.
    held = asyncio.run(called(OPS_KEY, "/test/team_ops", "uc410_place_hold", {"account_id": "CHQ-2219"}))
    why = held.structured_content or {}
    check(
        "3 a write declared to run at once is refused over MCP until a person approves",
        held.is_error is True and why.get("reasons") == ["write needs an approval token"],
        why,
    )
    rows = data(ops.get("/v1/executions", params={"tool": "uc410_place_hold", "pageSize": 5}))["data"]
    check(
        "3 the refusal is in the log as an mcp call",
        bool(rows) and rows[0].get("channel") == "mcp" and rows[0]["decision"] == "deny",
        rows[:1],
    )
    again = asyncio.run(called(OPS_KEY, "/test/team_ops", "uc410_get_account", {"account_id": "CHQ-2219"}))
    check("3 the bank holds nothing on the account", (again.structured_content or {}).get("holds") == [], again)

    # 4. Another team: its own URL lists none of team_ops' module and cannot run it; team_ops' URL refuses its key.
    fraud_seen = asyncio.run(listed(FRAUD_KEY, "/test/team_fraud"))
    check("4 a team_fraud key does not see team_ops' module", "uc410_get_account" not in fraud_seen, sorted(fraud_seen))
    stolen = asyncio.run(called(FRAUD_KEY, "/test/team_fraud", "uc410_get_account", {"account_id": "CHQ-2219"}))
    check(
        "4 calling it by name is refused as another team's",
        stolen.is_error is True and (stolen.structured_content or {}).get("code") == "team_forbidden",
        stolen,
    )
    check("4 a team_fraud key at team_ops' URL is 403", refused(FRAUD_KEY, "/test/team_ops") == (403, "team_forbidden"))

    # 5. Production is refused until a team allows it; no key is 401; a viewer, who cannot run tools, is 403.
    check("5 the production URL is 403", refused(OPS_KEY, "/production/team_ops") == (403, "production_off"))
    check("5 no credential is 401", refused(None, "/test/team_ops") == (401, "unauthorized"))
    check(
        "5 a viewer's token is refused (no tools.run)",
        refused(ravi.get("token", ""), "/test/team_ops") == (403, "role_required"),
    )
finish()
