"""An MCP server's sign-in found from the server (c-331): its 401 names the resource metadata, the metadata names the
authorization server, and an issuer that is not that server is refused; a server that answers needs no sign-in, and
an address off the allow-list is never fetched."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ops_tools.auth.discovery import Discovery
from ops_tools.auth.tokens import AuthFailed
from ops_tools.egress import EgressDenied

AUTH = Path(__file__).resolve().parents[1] / "scripts" / "fake_bank" / "bank_auth.py"
SERVER = "https://api.bank.test/mcp/screening"


def _bank_auth() -> Any:
    spec = importlib.util.spec_from_file_location("bank_auth_signin", AUTH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Listed:
    def __init__(self, refused: str | None = None) -> None:
        self.refused = refused
        self.checked: list[str] = []

    async def check_url(self, tenant_id: str, url: str) -> str:
        self.checked.append(url)
        if self.refused and self.refused in url:
            raise EgressDenied("not on the allow-list")
        return url


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.bank.test")


async def test_the_sign_in_is_found_from_the_servers_401() -> None:
    app = FastAPI()
    app.include_router(_bank_auth().router)
    found = await Discovery(_client(app), Listed()).find("t", SERVER)  # pyright: ignore[reportArgumentType]
    assert found is not None
    assert (found.resource, found.issuer) == (SERVER, "https://api.bank.test/oauth2")
    assert found.authorize_url == "https://api.bank.test/oauth2/authorize"
    assert found.token_url == "https://api.bank.test/oauth2/token"
    assert found.registration_url == "https://api.bank.test/oauth2/register"
    assert found.scopes == "screening.read"


async def test_an_issuer_that_is_not_the_named_server_is_refused() -> None:
    app = FastAPI()

    @app.post("/mcp/screening")
    def server() -> JSONResponse:
        challenge = (
            'Bearer resource_metadata="https://api.bank.test/.well-known/oauth-protected-resource/mcp/screening"'
        )
        return JSONResponse({}, status_code=401, headers={"WWW-Authenticate": challenge})

    @app.get("/.well-known/oauth-protected-resource/mcp/screening")
    def prm() -> dict[str, Any]:
        return {"resource": SERVER, "authorization_servers": ["https://api.bank.test/oauth2"]}

    @app.get("/.well-known/oauth-authorization-server/oauth2")
    def meta() -> dict[str, Any]:
        return {
            "issuer": "https://login.elsewhere.test",
            "authorization_endpoint": "https://login.elsewhere.test/authorize",
            "token_endpoint": "https://login.elsewhere.test/token",
        }

    with pytest.raises(AuthFailed, match="different issuer"):
        await Discovery(_client(app), Listed()).find("t", SERVER)  # pyright: ignore[reportArgumentType]


async def test_a_server_that_answers_needs_no_sign_in() -> None:
    app = FastAPI()

    @app.post("/mcp/open")
    def server() -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": 1, "result": {}}

    assert await Discovery(_client(app), Listed()).find("t", "https://api.bank.test/mcp/open") is None  # pyright: ignore[reportArgumentType]


async def test_metadata_on_an_unlisted_host_is_not_fetched() -> None:
    app = FastAPI()
    app.include_router(_bank_auth().router)
    policy = Listed(refused="/.well-known/oauth-authorization-server")
    with pytest.raises(AuthFailed) as refused:
        await Discovery(_client(app), policy).find("t", SERVER)  # pyright: ignore[reportArgumentType]
    assert refused.value.code == "EGRESS_DENIED"
    assert policy.checked[-1].endswith("/.well-known/oauth-authorization-server/oauth2")
