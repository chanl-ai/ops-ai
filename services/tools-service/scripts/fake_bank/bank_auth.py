"""The bank stand-in's sign-in: an OAuth 2.0 server and routes protected each way a connection signs in (c-330).

Every protected route answers which credential arrived and for which environment, so a use case can tell that a call
carried the test value and not the production one. None of it is in the bank's OpenAPI document: importing the core
banking API brings none of these operations along.

| Route | Accepts |
|---|---|
| `GET /auth/api-key` | `X-Api-Key` header or `api_key` query: `FAKE_BANK_TEST_KEY` or `FAKE_BANK_PROD_KEY` |
| `GET /auth/basic` | Basic `ops-test:test-pass` or `ops-prod:prod-pass` |
| `GET /auth/bearer` | Bearer `test-bearer-token` or `prod-bearer-token` |
| `GET /auth/oauth`, `POST /auth/oauth/holds` | Bearer an access token this server issued and has not revoked |
| `POST /oauth2/token` | client_credentials, authorization_code with S256 PKCE, refresh_token (rotating) |
| `GET /oauth2/authorize` | Redirects at once to `redirect_uri` with a code and the state, as on consent |
| `POST /oauth2/revoke-access` | Test control: every access token issued so far stops working; refresh still works |
| `GET /oauth2/stats` | Test control: how many tokens each grant issued |
| `POST /mcp/screening` | An MCP server that answers only a token issued for it (`resource`) |
| `GET /.well-known/oauth-protected-resource/mcp/screening` | Its protected resource metadata (RFC 9728) |
| `GET /.well-known/oauth-authorization-server/oauth2` | The authorization server's metadata (RFC 8414) |
| `POST /oauth2/register` | Dynamic client registration of a public client (c-331) |
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from typing import Annotated, Any
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

router = APIRouter(include_in_schema=False)

KEYS = {
    os.environ.get("FAKE_BANK_TEST_KEY", "test-bank-key"): "test",
    os.environ.get("FAKE_BANK_PROD_KEY", "prod-bank-key"): "production",
}
USERS = {("ops-test", "test-pass"): "test", ("ops-prod", "prod-pass"): "production"}
BEARERS = {"test-bearer-token": "test", "prod-bearer-token": "production"}
# Registered clients and their secrets; a public client (no secret) proves itself with PKCE alone.
CLIENTS: dict[str, str | None] = {"ops-gateway": "cc-secret", "ops-console": "ac-secret"}
ACCOUNT = "svc-lending@bank.test"
TOKEN_TTL_S = int(os.environ.get("FAKE_BANK_TOKEN_TTL", "3600"))

# Issued state, in memory: access token -> who it is for; refresh token -> its grant; code -> its PKCE challenge.
ACCESS: dict[str, dict[str, Any]] = {}
REFRESH: dict[str, dict[str, Any]] = {}
CODES: dict[str, dict[str, Any]] = {}
# Tokens issued per grant, requests refused, and writes received at /auth/oauth/holds (counted before the token check).
STATS: dict[str, int] = {"client_credentials": 0, "authorization_code": 0, "refresh_token": 0, "refused": 0, "holds": 0}


def _refuse(error: str, status: int = 400) -> JSONResponse:
    STATS["refused"] += 1
    return JSONResponse({"error": error}, status_code=status)


def _id_token(email: str) -> str:
    """An unsigned id token carrying who signed in; the gateway shows it and decides nothing from it."""
    part = base64.urlsafe_b64encode(json.dumps({"sub": email, "email": email}).encode()).rstrip(b"=").decode()
    return f"e30.{part}."


def _issue(grant: str, client: str, *, refresh: bool, scope: str, resource: str | None = None) -> dict[str, Any]:
    access = "at_" + secrets.token_urlsafe(18)
    ACCESS[access] = {
        "client": client,
        "grant": grant,
        "expires": time.time() + TOKEN_TTL_S,
        "scope": scope,
        "resource": resource,
    }
    STATS[grant] += 1
    out: dict[str, Any] = {"access_token": access, "token_type": "Bearer", "expires_in": TOKEN_TTL_S, "scope": scope}
    if refresh:
        token = "rt_" + secrets.token_urlsafe(18)
        REFRESH[token] = {"client": client, "scope": scope, "resource": resource}
        out["refresh_token"] = token
        out["id_token"] = _id_token(ACCOUNT)
    return out


def _client(authorization: str | None, client_id: str | None, client_secret: str | None) -> tuple[str, str | None]:
    if authorization and authorization.startswith("Basic "):
        cid, _, secret = base64.b64decode(authorization[6:]).decode().partition(":")
        return cid, secret
    return client_id or "", client_secret


@router.post("/oauth2/token")
async def token(request: Request) -> JSONResponse:
    """Form-encoded, read by hand: the stand-in needs no multipart parser."""
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
    cid, secret = _client(request.headers.get("authorization"), form.get("client_id"), form.get("client_secret"))
    if cid not in CLIENTS or (secret is not None and secret != CLIENTS[cid]):
        return _refuse("invalid_client", 401)
    grant = form.get("grant_type")
    if grant == "client_credentials":
        if secret is None:
            return _refuse("invalid_client", 401)
        scope = form.get("scope") or "accounts.read"
        return JSONResponse(_issue("client_credentials", cid, refresh=False, scope=scope))
    if grant == "authorization_code":
        held = CODES.pop(form.get("code") or "", None)
        if held is None or held["client"] != cid or held["redirect_uri"] != form.get("redirect_uri"):
            return _refuse("invalid_grant")
        digest = hashlib.sha256((form.get("code_verifier") or "").encode()).digest()
        if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != held["challenge"]:
            return _refuse("invalid_grant")
        if held.get("resource") != form.get("resource"):
            return _refuse("invalid_target")
        return JSONResponse(
            _issue("authorization_code", cid, refresh=True, scope=held["scope"], resource=held["resource"])
        )
    if grant == "refresh_token":
        # Rotation: the refresh token is spent; using it again is refused.
        held = REFRESH.pop(form.get("refresh_token") or "", None)
        if held is None or held["client"] != cid:
            return _refuse("invalid_grant")
        if held.get("resource") and form.get("resource") != held["resource"]:
            return _refuse("invalid_target")
        return JSONResponse(
            _issue("refresh_token", cid, refresh=True, scope=held["scope"], resource=held.get("resource"))
        )
    return _refuse("unsupported_grant_type")


@router.get("/oauth2/authorize")
def authorize(request: Request) -> RedirectResponse:
    q = request.query_params
    if (
        q.get("response_type") != "code"
        or q.get("code_challenge_method") != "S256"
        or q.get("client_id") not in CLIENTS
    ):
        raise HTTPException(400, "unsupported request")
    code = "code_" + secrets.token_urlsafe(12)
    CODES[code] = {
        "client": q["client_id"],
        "redirect_uri": q.get("redirect_uri"),
        "challenge": q.get("code_challenge"),
        "scope": q.get("scope", ""),
        "resource": q.get("resource"),
    }
    return RedirectResponse(f"{q.get('redirect_uri')}?{urlencode({'code': code, 'state': q.get('state', '')})}", 302)


@router.post("/oauth2/revoke-access")
def revoke_access() -> dict[str, int]:
    revoked = len(ACCESS)
    ACCESS.clear()
    return {"revoked": revoked}


@router.get("/oauth2/stats")
def stats() -> dict[str, int]:
    return dict(STATS)


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    return authorization[7:]


@router.get("/auth/api-key")
def api_key(
    x_api_key: Annotated[str | None, Header()] = None, key: Annotated[str | None, Query(alias="api_key")] = None
) -> dict[str, str]:
    given = x_api_key or key
    if given not in KEYS:
        raise HTTPException(401, "missing or wrong API key")
    return {"via": "header" if x_api_key else "query", "environment": KEYS[given]}


@router.get("/auth/basic")
def basic(authorization: Annotated[str | None, Header()] = None) -> dict[str, str]:
    if not authorization or not authorization.startswith("Basic "):
        raise HTTPException(401, "missing basic credentials")
    user, _, password = base64.b64decode(authorization[6:]).decode().partition(":")
    if (user, password) not in USERS:
        raise HTTPException(401, "wrong username or password")
    return {"user": user, "environment": USERS[(user, password)]}


@router.get("/auth/bearer")
def bearer(authorization: Annotated[str | None, Header()] = None) -> dict[str, str]:
    given = _bearer(authorization)
    if given not in BEARERS:
        raise HTTPException(401, "wrong bearer token")
    return {"environment": BEARERS[given]}


def _issued(authorization: str | None) -> dict[str, Any]:
    held = ACCESS.get(_bearer(authorization))
    if held is None or held["expires"] < time.time():
        raise HTTPException(401, "invalid or expired token")
    return held


@router.get("/auth/oauth")
def oauth(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    held = _issued(authorization)
    return {"client": held["client"], "grant": held["grant"], "scope": held["scope"]}


@router.post("/auth/oauth/holds")
def oauth_hold(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    """A write behind the token: a use case shows a 401 here is not sent twice."""
    STATS["holds"] += 1
    held = _issued(authorization)
    return {"hold": "placed", "client": held["client"]}


@router.get("/auth/mtls")
def mtls() -> dict[str, bool]:
    """Served on the certificate-only listener too: reaching it there means the handshake took a client certificate."""
    return {"mtls": True}


# ── An MCP server behind OAuth (c-331) ───────────────────────────────────

BASE = "https://api.bank.test"
MCP_RESOURCE = f"{BASE}/mcp/screening"
ISSUER = f"{BASE}/oauth2"
MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "checkSanctions",
        "description": "Screen a name against the sanctions watchlists",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "country": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "getSanctionsResult",
        "description": "A screening result by its id",
        "inputSchema": {
            "type": "object",
            "properties": {"screeningId": {"type": "string"}},
            "required": ["screeningId"],
        },
    },
]


@router.get("/.well-known/oauth-protected-resource/mcp/screening")
def protected_resource() -> dict[str, Any]:
    return {"resource": MCP_RESOURCE, "authorization_servers": [ISSUER], "scopes_supported": ["screening.read"]}


@router.get("/.well-known/oauth-authorization-server/oauth2")
def authorization_server() -> dict[str, Any]:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{BASE}/oauth2/authorize",
        "token_endpoint": f"{BASE}/oauth2/token",
        "registration_endpoint": f"{BASE}/oauth2/register",
        "code_challenge_methods_supported": ["S256"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
    }


@router.post("/oauth2/register", status_code=201)
async def register(request: Request) -> dict[str, Any]:
    body: Any = await request.json()
    client_id = "dyn_" + secrets.token_urlsafe(8)
    # A public client: it proves itself with PKCE alone.
    CLIENTS[client_id] = None
    STATS["registered"] = STATS.get("registered", 0) + 1
    return {
        "client_id": client_id,
        "redirect_uris": body.get("redirect_uris", []),
        "token_endpoint_auth_method": "none",
    }


def _rpc(rid: Any, result: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": result})


@router.post("/mcp/screening")
async def mcp_screening(request: Request) -> Any:
    auth = request.headers.get("authorization") or ""
    held = ACCESS.get(auth[7:]) if auth.startswith("Bearer ") else None
    if held is None or held["expires"] < time.time() or held.get("resource") != MCP_RESOURCE:
        STATS["mcp_refused"] = STATS.get("mcp_refused", 0) + 1
        challenge = f'Bearer resource_metadata="{BASE}/.well-known/oauth-protected-resource/mcp/screening"'
        return JSONResponse({"error": "invalid_token"}, status_code=401, headers={"WWW-Authenticate": challenge})
    msg: Any = await request.json()
    method, rid = msg.get("method"), msg.get("id")
    if method == "notifications/initialized":
        return JSONResponse(None, status_code=202)
    if method == "initialize":
        return _rpc(
            rid, {"protocolVersion": "2025-06-18", "serverInfo": {"name": "Compliance screening", "version": "2.0"}}
        )
    if method == "tools/list":
        return _rpc(rid, {"tools": MCP_TOOLS})
    if method == "tools/call":
        params: dict[str, Any] = msg.get("params") or {}
        STATS["mcp_calls"] = STATS.get("mcp_calls", 0) + 1
        found = {"tool": params.get("name"), "arguments": params.get("arguments"), "client": held["client"]}
        return _rpc(rid, {"content": [{"type": "text", "text": "screened"}], "structuredContent": found})
    return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}})
