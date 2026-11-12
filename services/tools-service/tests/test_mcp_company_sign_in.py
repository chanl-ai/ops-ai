"""A person connects an assistant to a team's MCP address with their company sign-in, as tools-service sees it, by
failure mode: a client that cannot find where to sign in, a token that works somewhere it was not issued for, a call
log that trusts the assistant's own name, and a second place that verifies tokens.

The address is <OPS_PLATFORM_PUBLIC_URL>/mcp/<team>; platform-service is its authorization server."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import Ed25519Signer, mint

from . import test_mcp_server
from .test_mcp_server import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]  (the fixture)

PUBLIC = "https://ops.bank.test"
ADDRESS = f"{PUBLIC}/mcp/team_lending"
PLATFORM = Ed25519Signer.generate("platform-1")
BODY: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
ACCEPT = {"Accept": "application/json, text/event-stream"}


@pytest.fixture(autouse=True)
def issuer_url(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str | None:
    """The install's public URL, set before the `stack` fixture builds the app; a test parametrizes it with None for
    an install that names no issuer."""
    url: str | None = getattr(request, "param", PUBLIC)
    if url is None:
        monkeypatch.delenv("OPS_PLATFORM_PUBLIC_URL", raising=False)
    else:
        monkeypatch.setenv("OPS_PLATFORM_PUBLIC_URL", url)
    return url


@pytest.fixture(autouse=True)
def platform_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """platform-service's published keys, which the stack's identity fetches in place of an empty set."""

    async def jwks() -> dict[str, Any]:
        return {"keys": [PLATFORM.public_jwk()]}

    monkeypatch.setattr(test_mcp_server, "no_keys", jwks)


def token(*, aud: list[str], **over: Any) -> str:
    claims: dict[str, Any] = {
        "sub": "usr_ana",
        "email": "ana@bank.test",
        "name": "Ana Ops",
        "tenant_id": over.pop("tenant_id"),
        "team_ids": ["team_lending"],
        "roles": {"team_lending": "builder"},
        "kind": "person",
        "auth_method": "password",
        "aud": aud,
        "sid": "ses_1",
        **over,
    }
    return mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)


# uc-mcp-1
@pytest.mark.parametrize("issuer_url", [PUBLIC, None], ids=["issuer-set", "no-issuer"], indirect=True)
async def test_a_client_with_no_token_is_told_where_to_sign_in_or_why_it_cannot(
    stack: Stack,  # noqa: F811
    issuer_url: str | None,
) -> None:
    async with stack.http(None) as http:
        r = await http.post("/mcp/team_lending", json=BODY, headers=ACCEPT)
        if issuer_url is None:
            assert r.status_code == 503, r.text
            assert "issuer" in r.json()["error"]["message"].lower()
            return
        assert r.status_code == 401
        header = r.headers["www-authenticate"]
        meta_url = f"{PUBLIC}/.well-known/oauth-protected-resource/mcp/team_lending"
        assert f'resource_metadata="{meta_url}"' in header, header
        meta = await http.get("/.well-known/oauth-protected-resource/mcp/team_lending")
        assert meta.status_code == 200, meta.text
        assert meta.json()["resource"] == ADDRESS
        assert meta.json()["authorization_servers"] == [PUBLIC]


# uc-mcp-2, uc-mcp-3
async def test_a_token_works_only_at_the_address_it_was_issued_for_and_the_log_names_the_grants_client(
    stack: Stack,  # noqa: F811
) -> None:
    tenant = stack.api.tenant
    good = token(aud=[ADDRESS], tenant_id=tenant, client_id="cli_claude", team_ids=["team_lending"])
    elsewhere = token(aud=[f"{PUBLIC}/mcp/team_cards"], tenant_id=tenant, client_id="cli_claude")
    other_host = token(aud=["https://evil.example/mcp/team_lending"], tenant_id=tenant, client_id="cli_claude")
    # The console's own token: audience the services, no address.
    console = token(aud=["platform", "agents", "tools"], tenant_id=tenant)
    async with stack.running():
        for label, bad in {"other team": elsewhere, "other host": other_host, "console": console}.items():
            async with stack.http(bad) as http:
                r = await http.post("/mcp/team_lending", json=BODY, headers=ACCEPT)
            assert r.status_code == 401, (label, r.status_code, r.text)
        async with stack.http(good) as http, stack.client(http, "/mcp/team_lending") as c:
            listed = {t.name for t in (await c.list_tools()).tools}
            result = await c.call_tool("lookup_case", {"caseId": "CASE-4112"})
    assert "lookup_case" in listed
    assert result.is_error is False
    [row] = await stack.rows("lookup_case")
    assert row["sub"] == "usr_ana"
    assert row["client_id"] == "cli_claude", "the grant's client, not what the assistant says about itself"
    assert row["client_name"] != "pytest-assistant"


# uc-mcp-17
def test_no_tools_service_module_verifies_a_token_itself() -> None:
    """tools-service takes a caller from ops_identity (`bearer(resource=...)` and nothing else): no key set, no
    signature check on a platform token in its own code. code_runs.py verifies its own HMAC-signed run tokens, which
    are not platform tokens."""
    src = Path(__file__).parents[1] / "src" / "ops_tools"
    forbidden_modules = {"jwt", "jose", "authlib", "jwcrypto", "ops_identity.jwks"}
    forbidden_names = {"JwksCache", "Ed25519Verifier", "header_of"}
    found: list[str] = []
    for path in src.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names: set[str] = set()
            if isinstance(node, ast.Import):
                names = {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {node.module or ""} | {f"{node.module}.{a.name}" for a in node.names}
                if forbidden_names & {a.name for a in node.names}:
                    found.append(f"{path.name}: imports a key-set or signature verifier")
            if any(n == m or n.startswith(m + ".") for n in names for m in forbidden_modules):
                found.append(f"{path.name}: imports {sorted(names)}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "verifier":
                found.append(f"{path.name}:{node.lineno}: asks a key set for a verifier")
    assert not found, found
