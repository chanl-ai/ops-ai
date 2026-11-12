"""uc-733 a person connects an assistant to a team's MCP address with their company sign-in, api layer:
docs/usecases/platform-service/mcp-company-sign-in.md. Real platform-service and tools-service; the client is scripted
with raw HTTP (registration, PKCE, consent, token). No model call."""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlsplit

from usecase_harness import (
    AGENTS_PORT,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    bearer,
    check,
    data,
    finish,
    platform,
    signed_in,
    tools,
)

PUBLIC = f"http://127.0.0.1:{PLATFORM_PORT}"
ADDRESS = f"{PUBLIC}/mcp/team_ops"
REDIRECT = "https://claude.example/callback"
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": PUBLIC,
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
ACCEPT = {"Accept": "application/json, text/event-stream"}

with (
    platform(env={"OPS_PLATFORM_PUBLIC_URL": PUBLIC}) as (api, _),
    tools(
        {
            **AUTH,
            "OPS_FLAGS": "mcp_gateway",
            "OPS_PLATFORM_PUBLIC_URL": PUBLIC,
            "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}",
        }
    ) as gateway,
):
    r = gateway.post("/mcp/team_ops", json=LIST, headers=ACCEPT)
    header = r.headers.get("www-authenticate", "")
    meta_url = f"{PUBLIC}/.well-known/oauth-protected-resource/mcp/team_ops"
    check(
        "no token at the MCP address is 401 and names the resource metadata",
        r.status_code == 401 and meta_url in header,
        header,
    )
    meta = gateway.get("/.well-known/oauth-protected-resource/mcp/team_ops")
    check(
        "the metadata names platform-service as the authorization server",
        meta.status_code == 200 and meta.json().get("authorization_servers") == [PUBLIC],
        meta.text[:200],
    )
    server = api.get("/.well-known/oauth-authorization-server")
    check(
        "the server metadata lists S256 only",
        server.status_code == 200 and server.json().get("code_challenge_methods_supported") == ["S256"],
        server.text[:200],
    )

    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    reg = api.post(
        "/oauth/register",
        json={
            "client_name": "uc-733 assistant",
            "redirect_uris": [REDIRECT],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    check("the client registers (201)", reg.status_code == 201, reg.text[:200])
    client_id = reg.json().get("client_id", "")
    james = signed_in(api, "j.richardson@harborpine.example")
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": ADDRESS,
        "state": "s1",
    }
    allowed = api.post("/v1/oauth/consent", json={**params, "decision": "allow"}, headers=bearer(james))
    check("James allows the assistant (200)", allowed.status_code == 200, allowed.text[:200])
    code = parse_qs(urlsplit(data(allowed)["redirectTo"]).query)["code"][0] if allowed.status_code == 200 else ""
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_verifier": verifier,
        "resource": ADDRESS,
    }
    got = api.post("/oauth/token", data=form)
    check("the code is exchanged for a token (200)", got.status_code == 200, got.text[:200])
    token = got.json().get("access_token") or "none"
    renewal = got.json().get("refresh_token") or "none"

    r = gateway.post("/mcp/team_ops", json=LIST, headers={**ACCEPT, "Authorization": f"Bearer {token}"})
    check("tools/list with the token lists James's tools (200)", r.status_code == 200, r.text[:200])
    r = gateway.post("/mcp/team_ops", json=LIST, headers={**ACCEPT, **bearer(james)})
    check("a console token is refused at the MCP address (401)", r.status_code == 401, r.status_code)
    r = gateway.post("/mcp/team_security", json=LIST, headers={**ACCEPT, "Authorization": f"Bearer {token}"})
    check("the token is refused at another team's address (401)", r.status_code == 401, r.status_code)

    priya = bearer(signed_in(api, "p.shah@harborpine.example"), "team_ops")
    rows = api.get("/v1/settings/members", headers=priya).json()["data"]["data"]
    james_row = next(m["id"] for m in rows if m["email"].startswith("j.richardson"))
    gone = api.post("/v1/settings/members/delete", json={"ids": [james_row]}, headers=priya)
    check("Priya removes James from team_ops (200)", gone.status_code == 200, gone.text[:200])
    renew = api.post(
        "/oauth/token", data={"grant_type": "refresh_token", "refresh_token": renewal, "client_id": client_id}
    )
    check(
        "James's assistant cannot renew after he left the team (400 invalid_grant)",
        renew.status_code == 400 and renew.json().get("error") == "invalid_grant",
        renew.text[:200],
    )

finish()
