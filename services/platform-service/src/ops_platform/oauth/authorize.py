"""The browser half of connecting an assistant: `GET /oauth/authorize` checks the request and sends the browser to the
console's consent page; the page reads what it shows from `GET /v1/oauth/consent` and sends the person's answer to
`POST /v1/oauth/consent`, with the person's console sign-in. The address names the team (`<public URL>/mcp/<team>`),
so there is no team to choose, and a person outside that team is refused.

A request is refused, and never redirected, when the redirect address is not one the assistant registered, the
challenge is missing or not S256, or the resource is not the MCP address of an active team on this install."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

from ops_access import can
from ops_service_kit.errors import Forbidden, Unauthorized, Unprocessable
from ops_service_kit.ids import new_id

from ..auth import Auth
from ..store.identity import Client, IdentityStore, SessionRef
from ..store.policies import PolicyStore
from . import OAuthError, iso
from .clients import redirect_allowed

CODE_TTL_S = 600
TEAM_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CHALLENGE = re.compile(r"^[A-Za-z0-9_~.-]{43,128}$")
CLIENTS_PER_TENANT = 500
DEFAULT_HOURS = 8


def code_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


@dataclass(frozen=True)
class Request:
    client: Client
    redirect_uri: str
    code_challenge: str
    resource: str
    team_id: str
    tenant_id: str
    state: str | None


def redirect_host(uri: str) -> str:
    """The place the browser goes back to, as the person should read it: the host (and port), or an app's scheme."""
    p = urlsplit(uri)
    if not p.hostname:
        return f"{p.scheme}:"
    return f"{p.hostname}:{p.port}" if p.port else p.hostname


@dataclass
class Authorizer:
    store: IdentityStore
    auth: Auth
    policies: PolicyStore
    # tools-service's public base, where a team's MCP address lives; not this service's own, which a proxy serves
    # under another path.
    mcp_url: str | None
    console_url: str | None

    def _base(self) -> str:
        if not self.mcp_url:
            raise OAuthError(
                "server_error", "This install names no public address for its MCP service (OPS_TOOLS_PUBLIC_URL).",
                status=503,
            )  # fmt: skip
        return self.mcp_url.rstrip("/")

    async def check(self, q: dict[str, str]) -> Request:
        base = self._base()
        client_id = q.get("client_id", "")
        client = await self.store.client(client_id) if 0 < len(client_id) <= 64 else None
        if client is None:
            raise OAuthError("invalid_client", "This assistant is not registered with this install.")
        uri = q.get("redirect_uri", "")
        if not redirect_allowed(client, uri):
            raise OAuthError("invalid_request", "That return address is not one this assistant registered.")
        challenge = q.get("code_challenge", "")
        if not CHALLENGE.match(challenge) or q.get("code_challenge_method") != "S256":
            raise OAuthError("invalid_request", "A PKCE challenge made with S256 is required.")
        resource = q.get("resource", "")
        team_id = resource.removeprefix(f"{base}/mcp/") if resource.startswith(f"{base}/mcp/") else ""
        found = await self.store.team_tenant(team_id) if TEAM_ID.match(team_id) else None
        if found is None:
            raise OAuthError("invalid_target", "That address is not a team's MCP address on this install.")
        return Request(client, uri, challenge, f"{base}/mcp/{team_id}", team_id, found[0], q.get("state"))

    async def start(self, q: dict[str, str]) -> str:
        """Where the browser goes to ask the person, once the request has checked out."""
        if q.get("response_type") != "code":
            raise OAuthError("unsupported_response_type", "Only response_type=code is taken.")
        await self.check(q)
        if not self.console_url:
            raise OAuthError("server_error", "This install names no console address (OPS_CONSOLE_URL).", status=503)
        return f"{self.console_url.rstrip('/')}/oauth/authorize?{urlencode(q)}"

    async def _member(self, claims: dict[str, Any], req: Request) -> None:
        """The person must be in the address's team, in the team's own workspace, and may run tools there."""
        in_team = req.team_id in [str(t) for t in claims.get("team_ids") or []]
        if not in_team or req.tenant_id != str(claims["tenant_id"]):
            raise Forbidden("You are not a member of that team.", code="team_forbidden")
        can(Auth.person_in_team(claims, req.team_id), "tools", "run", team=req.team_id, what="this team's tools")

    async def _hours(self, tenant_id: str) -> int:
        value = (await self.policies.values(tenant_id)).get("mcpConnectionHours", DEFAULT_HOURS)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else DEFAULT_HOURS

    async def show(self, claims: dict[str, Any], q: dict[str, str]) -> dict[str, Any]:
        req = await self.check(q)
        await self._member(claims, req)
        return {
            "client": {"id": req.client.id, "name": req.client.name, "nameIsSelfReported": True},
            "redirectHost": redirect_host(req.redirect_uri),
            "team": {"id": req.team_id, "name": await self.store.team_name(req.tenant_id, req.team_id) or req.team_id},
            "resource": req.resource,
            "connectionHours": await self._hours(req.tenant_id),
        }

    async def decide(
        self, claims: dict[str, Any], q: dict[str, str], *, allow: bool, request_id: str
    ) -> dict[str, Any]:
        req = await self.check(q)
        await self._member(claims, req)
        sep = "&" if "?" in req.redirect_uri else "?"
        if not allow:
            back = {"error": "access_denied", **({"state": req.state} if req.state else {})}
            return {"redirectTo": f"{req.redirect_uri}{sep}{urlencode(back)}"}
        tenant = str(claims["tenant_id"])
        if req.client.consented_at is None and await self.store.clients_of_tenant(tenant) >= CLIENTS_PER_TENANT:
            raise Unprocessable(
                f"This workspace already has {CLIENTS_PER_TENANT} assistants. Disconnect some first.",
                code="too_many_clients",
            )
        user = await self.store.user(tenant, str(claims["sub"]))
        method = await self.store.method(SessionRef(tenant, str(claims["sub"]), str(claims["sid"])))
        if user is None or method is None:
            raise Unauthorized("Sign in again.")
        now = datetime.now(UTC)
        session_id, secret = new_id("ses"), secrets.token_urlsafe(32)
        code = f"{session_id}.{secret}"
        await self.store.open_grant(
            user,
            client=req.client,
            session_id=session_id,
            auth_method=method.auth_method,
            team_id=req.team_id,
            resource=req.resource,
            code_hash=code_hash(code),
            code_challenge=req.code_challenge,
            redirect_uri=req.redirect_uri,
            code_expires_at=iso(now + timedelta(seconds=CODE_TTL_S)),
            expires_at=iso(now + timedelta(hours=await self._hours(tenant))),
            at=iso(now),
            request_id=request_id,
        )
        back = {"code": code, **({"state": req.state} if req.state else {})}
        return {"redirectTo": f"{req.redirect_uri}{sep}{urlencode(back)}"}
