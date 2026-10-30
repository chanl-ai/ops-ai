"""Test connection (c-558), by failure mode: the test signs in with an account other than the one asked for, a builder
tests the team's account, a failed test is stored as a pass or one person's missing sign-in marks the whole connection,
and a connection with no test address is tested against something it never named."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_policy import AesGcmCipher
from ops_service_kit.settings import Settings
from ops_tools.auth.tokens import Tokens
from ops_tools.modules.seed import load
from ops_tools.store.connections import SHARED, ConnectionStore
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, response_checker
from .test_review_decisions import introspect, jwks, person

TEAM = "team_platform"
SETTINGS = {
    "baseUrl": "https://crm.bank.test",
    "authorizeUrl": "https://login.bank.test/authorize",
    "tokenUrl": "https://login.bank.test/token",
    "clientId": "ops-console",
    "testPath": "/me",
}


class System:
    """The connected system: answers its test address by the token it is sent, and records each token."""

    def __init__(self) -> None:
        self.seen: list[str] = []
        self.answers: dict[str, int] = {"at-team": 200, "at-james": 200}

    def client(self) -> httpx.AsyncClient:
        async def answer(request: httpx.Request) -> httpx.Response:
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            if request.url.path == "/token":
                # The system refuses every refresh, as it does once the account's grant is revoked.
                return httpx.Response(400, json={"error": "invalid_grant"})
            self.seen.append(token)
            if request.url.path != "/me":
                return httpx.Response(404)
            return httpx.Response(self.answers.get(token, 401), json={"user": token})

        return httpx.AsyncClient(transport=httpx.MockTransport(answer))


@pytest.fixture
def system() -> System:
    return System()


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], system: System
) -> AsyncIterator[httpx.AsyncClient]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    app = build_app(engine, seed, tenant, auth=auth, upstream=system.client())
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield c


PRIYA = ("Priya Shah", {TEAM: "admin"})
JAMES = ("James Richardson", {TEAM: "builder"})
MAYA = ("Maya Okafor", {TEAM: "builder"})


async def connection(client: httpx.AsyncClient, engine: AsyncEngine, tenant: str, settings: dict[str, str]) -> str:
    """A connection each person signs in to, with the team's sign-in and James's own already held."""
    admin = person(tenant, *PRIYA)
    security = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    for host in ("login.bank.test", "crm.bank.test"):
        await client.post("/v1/egress/hosts", json={"value": host}, headers=security)
    made = await client.post(
        "/v1/connections", json={"name": "CRM", "authKind": "oauth2_auth_code", "signIn": "person"}, headers=admin
    )
    assert made.status_code == 201, made.text
    conn = str(made.json()["data"]["id"])
    put = await client.put(
        f"/v1/connections/{conn}/environments/test", json={"revision": 1, "settings": settings}, headers=admin
    )
    assert put.status_code == 200, put.text
    for who, token in ((SHARED, "at-team"), ("usr_james", "at-james")):
        await tokens(engine).store_answer(tenant, conn, "test", {"access_token": token, "expires_in": 3600}, who)
    return conn


def tokens(engine: AsyncEngine) -> Tokens:
    return Tokens(ConnectionStore(engine), AesGcmCipher(Settings().secrets_key.get_secret_value()), None, None)  # pyright: ignore[reportArgumentType]


async def press_test(
    client: httpx.AsyncClient, tenant: str, conn: str, who: tuple[str, dict[str, str]], **body: str
) -> httpx.Response:
    return await client.post(
        f"/v1/connections/{conn}/test", json={"environment": "test", **body}, headers=person(tenant, *who)
    )


async def test_the_test_signs_in_with_the_account_asked_for_and_stores_whose_it_was(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str, system: System
) -> None:
    conn = await connection(client, engine, tenant, SETTINGS)
    own = await press_test(client, tenant, conn, JAMES)
    assert own.status_code == 200, own.text
    health = own.json()["data"]["health"]
    assert system.seen == ["at-james"]
    assert (health["status"], health["account"], health["environment"]) == ("ok", "own", "test"), health
    assert isinstance(health["latencyMs"], int) and health["at"] and health["by"]
    refused = await press_test(client, tenant, conn, JAMES, account="team")
    assert refused.status_code == 403, refused.text
    team = await press_test(client, tenant, conn, PRIYA, account="team")
    assert team.status_code == 200, team.text
    assert system.seen == ["at-james", "at-team"]
    assert team.json()["data"]["health"]["account"] == "team"


async def test_a_failed_test_is_stored_and_only_the_team_accounts_failure_marks_the_connection(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str, system: System
) -> None:
    conn = await connection(client, engine, tenant, SETTINGS)
    unlinked = await press_test(client, tenant, conn, MAYA)
    assert unlinked.status_code == 200, unlinked.text
    data = unlinked.json()["data"]
    assert (data["health"]["status"], data["health"]["code"]) == ("failed", "CONNECTION_NOT_LINKED"), data["health"]
    assert data["status"] == "healthy" and system.seen == []
    system.answers["at-team"] = 503
    down = await press_test(client, tenant, conn, PRIYA, account="team")
    assert down.status_code == 200, down.text
    data = down.json()["data"]
    assert (data["health"]["status"], data["health"]["httpStatus"]) == ("failed", 503), data["health"]
    assert data["status"] == "error" and data["statusDetail"]


async def test_a_team_sign_in_the_system_refuses_leaves_the_connection_needing_reconnect(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str, system: System
) -> None:
    conn = await connection(client, engine, tenant, SETTINGS)
    spent = {"access_token": "at-old", "refresh_token": "rt-old", "expires_in": 1}
    await tokens(engine).store_answer(tenant, conn, "test", spent, SHARED)
    r = await press_test(client, tenant, conn, PRIYA, account="team")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["health"]["status"] == "failed" and data["status"] == "needs_reconnect", data


async def test_a_connection_with_no_test_address_is_not_tested(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str, system: System
) -> None:
    conn = await connection(client, engine, tenant, {k: v for k, v in SETTINGS.items() if k != "testPath"})
    r = await press_test(client, tenant, conn, PRIYA, account="team")
    assert r.status_code == 400 and r.json()["error"]["code"] == "test_path_missing", r.text
    assert system.seen == []
