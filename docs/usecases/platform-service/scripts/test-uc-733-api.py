"""uc-733 a person connects an assistant to a team's MCP address with their company sign-in, api layer:
docs/usecases/platform-service/mcp-company-sign-in.md. Real platform-service and tools-service behind the real proxy
(deploy/fly/Caddyfile in Caddy, as compose, k8s and Fly serve one origin). Discovery runs the MCP Python SDK's own
discovery steps from the 401; the rest of the client is scripted with raw HTTP (registration, PKCE, consent, token).
No model call."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from typing import Any

import httpx
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    extract_resource_metadata_from_www_auth,
    handle_auth_metadata_response,
    handle_protected_resource_response,
)
from usecase_harness import (
    AGENTS_PORT,
    PLATFORM_INTERNAL_PORT,
    assistant_sign_in,
    bearer,
    check,
    finish,
    platform,
    proxy,
    signed_in,
    tools,
)

LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
ACCEPT = {"Accept": "application/json, text/event-stream"}


async def discover(address: str) -> tuple[str, list[str], dict[str, Any] | None, str]:
    """What an MCP client does with a 401 from `address`, in the SDK's order: the resource metadata, then the
    authorization server's metadata at each URL the SDK builds from its issuer, stopping at the first it can read.
    Returns the header, the URLs tried, the server metadata found and the issuer it was found for."""
    # Over Caddy's 30 s wait for an upstream: a path the proxy sends to the console, which this run does not start,
    # answers 502 rather than timing out.
    async with httpx.AsyncClient(timeout=40) as web:
        first = await web.post(address, json=LIST, headers=ACCEPT)
        header = first.headers.get("www-authenticate", "")
        tried: list[str] = []
        resource = None
        for url in build_protected_resource_metadata_discovery_urls(
            extract_resource_metadata_from_www_auth(first),
            address,  # pyright: ignore[reportArgumentType]
        ):
            tried.append(url)
            resource = await handle_protected_resource_response(await web.get(url))  # pyright: ignore[reportArgumentType]
            if resource is not None:
                break
        if resource is None or not resource.authorization_servers:
            return header, tried, None, ""
        issuer = str(resource.authorization_servers[0])
        for url in build_oauth_authorization_server_metadata_discovery_urls(issuer, address):
            tried.append(url)
            go_on, found = await handle_auth_metadata_response(await web.get(url))  # pyright: ignore[reportArgumentType]
            if found is not None:
                return header, tried, found.model_dump(mode="json"), issuer
            if not go_on:
                break
        return header, tried, None, issuer


with ExitStack() as stack:
    origin = stack.enter_context(proxy())
    PUBLIC = f"{origin}/api/platform"
    TOOLS_PUBLIC = f"{origin}/api/tools"
    ADDRESS = f"{TOOLS_PUBLIC}/mcp/team_ops"
    URLS = {"OPS_PLATFORM_PUBLIC_URL": PUBLIC, "OPS_TOOLS_PUBLIC_URL": TOOLS_PUBLIC}
    api, _ = stack.enter_context(platform(env=URLS))
    gateway = stack.enter_context(
        tools(
            {
                "OPS_AUTH_MODE": "platform",
                "OPS_PLATFORM_URL": str(api.base_url).rstrip("/"),
                "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
                "OPS_FLAGS": "mcp_gateway",
                "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}",
                **URLS,
            }
        )
    )

    header, tried, server, issuer = asyncio.run(discover(ADDRESS))
    meta_url = f"{TOOLS_PUBLIC}/.well-known/oauth-protected-resource/mcp/team_ops"
    check(
        "1 no token at the team's address, through the proxy, is 401 and names the resource metadata",
        f'resource_metadata="{meta_url}"' in header,
        header,
    )
    check("1 the resource metadata names platform-service as the authorization server", issuer == PUBLIC, tried)
    check(
        "1 the MCP SDK finds the server metadata through the proxy from the 401, for the issuer it was told",
        server is not None and server.get("issuer") == issuer,
        tried,
    )
    check(
        "1 the server metadata lists S256 only",
        server is not None and server.get("code_challenge_methods_supported") == ["S256"],
        server,
    )

    signin = assistant_sign_in(api, "j.richardson@harborpine.example", ADDRESS, client_name="uc-733 assistant")
    client_id, token, renewal = signin["client_id"], signin["access_token"], signin["refresh_token"]
    james = {"token": signin["person_token"]}

    r = gateway.post("/mcp/team_ops", json=LIST, headers={**ACCEPT, "Authorization": f"Bearer {token}"})
    check("3 tools/list with the token lists James's tools (200)", r.status_code == 200, r.text[:200])
    r = gateway.post("/mcp/team_ops", json=LIST, headers={**ACCEPT, **bearer(james)})
    check("4 a console token is refused at the MCP address (401)", r.status_code == 401, r.status_code)
    r = gateway.post("/mcp/team_security", json=LIST, headers={**ACCEPT, "Authorization": f"Bearer {token}"})
    check("4 the token is refused at another team's address (401)", r.status_code == 401, r.status_code)

    priya = bearer(signed_in(api, "p.shah@harborpine.example"), "team_ops")
    rows = api.get("/v1/settings/members", headers=priya).json()["data"]["data"]
    james_row = next(m["id"] for m in rows if m["email"].startswith("j.richardson"))
    gone = api.post("/v1/settings/members/delete", json={"ids": [james_row]}, headers=priya)
    check("5 Priya removes James from team_ops (200)", gone.status_code == 200, gone.text[:200])
    renew = api.post(
        "/oauth/token", data={"grant_type": "refresh_token", "refresh_token": renewal, "client_id": client_id}
    )
    check(
        "5 James's assistant cannot renew after he left the team (400 invalid_grant)",
        renew.status_code == 400 and renew.json().get("error") == "invalid_grant",
        renew.text[:200],
    )

finish()
