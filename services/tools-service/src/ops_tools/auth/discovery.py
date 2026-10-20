"""How an MCP server signs in, found from the server itself (c-331), as the MCP authorization spec asks of a client.

The server answers an unsigned request with 401 and `WWW-Authenticate: Bearer resource_metadata="<url>"` (RFC 9728);
without the parameter the metadata is at `/.well-known/oauth-protected-resource<path>` on the server's origin. The
metadata names the resource and its authorization servers; the first one's metadata is read from
`/.well-known/oauth-authorization-server<path>` (RFC 8414), and its `issuer` must be exactly the server the resource
named, so a server cannot send the sign-in to someone else's endpoints. Every request goes through the egress client
and must reach a listed host; every address found must be https.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

from ..egress import EgressDenied, EgressPolicy, for_tenant
from .tokens import AuthFailed

TIMEOUT_S = 10.0
_RESOURCE_METADATA = re.compile(r'resource_metadata="([^"]+)"')
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "ops-tools-service"}},
}


@dataclass(frozen=True)
class SignIn:
    """What a connection needs to sign in to the server: c-330's authorization code settings, `resource` the server."""

    resource: str
    issuer: str
    authorize_url: str
    token_url: str
    registration_url: str | None
    scopes: str


def _well_known(url: str, name: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    return f"https://{parts.netloc}/.well-known/{name}{path}"


def _https(value: Any, what: str) -> str:
    if not isinstance(value, str) or urlsplit(value).scheme != "https":
        raise AuthFailed("SIGN_IN_NOT_FOUND", f"The server's {what} is not an https address.")
    return value


class Discovery:
    def __init__(self, http: httpx.AsyncClient, policy: EgressPolicy) -> None:
        self.http = http
        self.policy = policy

    async def _get(self, tenant_id: str, url: str) -> dict[str, Any]:
        try:
            await self.policy.check_url(tenant_id, url)
            res = await self.http.get(url, timeout=TIMEOUT_S, extensions=for_tenant(tenant_id))
        except EgressDenied as e:
            raise AuthFailed("EGRESS_DENIED", str(e)) from e
        except httpx.HTTPError as e:
            raise AuthFailed("SIGN_IN_NOT_FOUND", f"{urlsplit(url).hostname} could not be reached.") from e
        try:
            body: Any = res.json()
        except ValueError:
            body = None
        if res.status_code >= 400 or not isinstance(body, dict):
            raise AuthFailed(
                "SIGN_IN_NOT_FOUND", f"{urlsplit(url).hostname} has no sign-in metadata at {urlsplit(url).path}."
            )
        return cast(dict[str, Any], body)

    async def find(self, tenant_id: str, server_url: str) -> SignIn | None:
        """The server's sign-in, or None when it answers without asking for one."""
        try:
            await self.policy.check_url(tenant_id, server_url)
            res = await self.http.post(
                server_url,
                json=INITIALIZE,
                headers={"Accept": "application/json, text/event-stream"},
                timeout=TIMEOUT_S,
                extensions=for_tenant(tenant_id),
            )
        except EgressDenied as e:
            raise AuthFailed("EGRESS_DENIED", str(e)) from e
        except httpx.HTTPError as e:
            raise AuthFailed("SIGN_IN_NOT_FOUND", f"{urlsplit(server_url).hostname} could not be reached.") from e
        if res.status_code != 401:
            return None
        found = _RESOURCE_METADATA.search(res.headers.get("www-authenticate", ""))
        prm_url = found.group(1) if found else _well_known(server_url, "oauth-protected-resource")
        prm = await self._get(tenant_id, _https(prm_url, "resource metadata address"))
        if prm.get("resource") not in (server_url, server_url.rstrip("/")):
            raise AuthFailed("SIGN_IN_NOT_FOUND", "The server's resource metadata describes another address.")
        servers = prm.get("authorization_servers")
        if not isinstance(servers, list) or not servers:
            raise AuthFailed("SIGN_IN_NOT_FOUND", "The server's resource metadata names no authorization server.")
        issuer = _https(cast(list[Any], servers)[0], "authorization server")
        meta = await self._get(tenant_id, _well_known(issuer, "oauth-authorization-server"))
        if meta.get("issuer") != issuer:
            raise AuthFailed(
                "SIGN_IN_NOT_FOUND", "The authorization server's metadata names a different issuer; not following it."
            )
        methods = meta.get("code_challenge_methods_supported")
        if isinstance(methods, list) and "S256" not in methods:
            raise AuthFailed("SIGN_IN_NOT_FOUND", "The authorization server does not offer PKCE with S256.")
        scopes = prm.get("scopes_supported")
        return SignIn(
            resource=server_url,
            issuer=issuer,
            authorize_url=_https(meta.get("authorization_endpoint"), "sign-in address"),
            token_url=_https(meta.get("token_endpoint"), "token address"),
            registration_url=_https(meta["registration_endpoint"], "registration address")
            if meta.get("registration_endpoint")
            else None,
            scopes=" ".join(str(s) for s in cast(list[Any], scopes)) if isinstance(scopes, list) else "",
        )

    async def register(self, tenant_id: str, registration_url: str, redirect_uri: str, name: str) -> str:
        """A public client registered with the server (dynamic client registration, offered by older servers)."""
        body = {
            "client_name": name,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
        try:
            await self.policy.check_url(tenant_id, registration_url)
            res = await self.http.post(registration_url, json=body, timeout=TIMEOUT_S, extensions=for_tenant(tenant_id))
        except EgressDenied as e:
            raise AuthFailed("EGRESS_DENIED", str(e)) from e
        except httpx.HTTPError as e:
            raise AuthFailed("SIGN_IN_NOT_FOUND", f"{urlsplit(registration_url).hostname} could not be reached.") from e
        answer: Any = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
        client_id = cast(dict[str, Any], answer).get("client_id") if isinstance(answer, dict) else None
        if res.status_code >= 400 or not isinstance(client_id, str) or not client_id:
            raise AuthFailed("SIGN_IN_NOT_FOUND", "The server refused to register a client; give a registered one.")
        return client_id
