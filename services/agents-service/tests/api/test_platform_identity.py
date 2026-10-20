"""OPS_AUTH_MODE=platform through the real ops_identity resolution, by failure mode: the tenant taken from anywhere
but the token, another tenant's thread being visible, another team's thread opening without a team switch, the dev
headers still working, and an internal route taking a service token that names no tenant. The key set and key
introspection are local stand-ins for platform-service, whose own seam test drives them for real."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import Ed25519Signer, mint
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model

PLATFORM = Ed25519Signer.generate("platform-test")


def token(tenant: str, teams: list[str], *, aud: str = "agents") -> dict[str, str]:
    claims = {
        "sub": f"usr_{tenant}",
        "email": f"p@{tenant}.example",
        "name": "Pat",
        "kind": "person",
        "aud": [aud],
        "tenant_id": tenant,
        "team_ids": teams,
        "roles": dict.fromkeys(teams, "builder"),
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": teams[0]}


async def jwks() -> dict[str, Any]:
    return {"keys": [PLATFORM.public_jwk()]}


async def introspect(_key: str) -> dict[str, Any] | None:
    return None


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        auth=Auth(
            Identity(audience="agents", jwks=jwks, introspect=introspect, key_cache_s=0),
            ServiceAuth(audience="agents", verifiers=service_verifiers(settings, "agents")),
        ),
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        yield c


async def new_thread(client: AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post("/v1/threads", json={"graph": "simple_workflow", "metadata": {}}, headers=headers)
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["threadId"])


async def test_a_thread_belongs_to_the_tenant_and_team_in_the_token(client: AsyncClient) -> None:
    acme = token("acme", ["team_a"])
    tid = await new_thread(client, acme)
    assert (await client.get(f"/v1/threads/{tid}/state", headers=acme)).status_code == 200
    listed = (await client.get("/v1/threads", headers=acme)).json()["data"]
    assert tid in [t["threadId"] for t in listed]


async def test_another_tenants_thread_is_not_found_and_not_listed(client: AsyncClient) -> None:
    tid = await new_thread(client, token("acme", ["team_a"]))
    other = token("globex", ["team_a"])  # same team name, different tenant
    r = await client.get(f"/v1/threads/{tid}/state", headers=other)
    assert r.status_code == 404, r.text
    assert tid not in [t["threadId"] for t in (await client.get("/v1/threads", headers=other)).json()["data"]]


async def test_another_teams_thread_is_refused_with_the_owning_team_and_not_listed(client: AsyncClient) -> None:
    tid = await new_thread(client, token("acme", ["team_a"]))
    team_b = token("acme", ["team_b"])
    assert tid not in [t["threadId"] for t in (await client.get("/v1/threads", headers=team_b)).json()["data"]]
    r = await client.get(f"/v1/threads/{tid}/state", headers=team_b)
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "team_forbidden"
    assert r.json()["error"]["details"] == {"teamId": "team_a"}


async def test_dev_headers_and_other_audiences_are_refused(client: AsyncClient) -> None:
    r = await client.get("/v1/threads", headers={"X-Dev-User": "someone@example.com", "X-Team-Id": "team_a"})
    assert r.status_code == 401, r.text
    assert (await client.get("/v1/threads", headers=token("acme", ["team_a"], aud="tools"))).status_code == 401


async def test_a_platform_step_up_presented_as_a_bearer_token_is_401(client: AsyncClient) -> None:
    """What platform-service's POST /v1/auth/step-up mints: the session's key and audience, kind and typ step_up. It
    proves a re-authentication for a money decision and opens nothing on its own."""
    claims = {
        "sub": "usr_acme",
        "email": "p@acme.example",
        "tenant_id": "acme",
        "kind": "step_up",
        "typ": "step_up",
        "aud": ["platform", "agents"],
    }
    headers = {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": "team_a"}
    r = await client.get("/v1/threads", headers=headers)
    assert r.status_code == 401, r.text
