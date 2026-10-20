"""Who may publish, pause or resume a v2 workflow, by failure mode: a builder pausing a workflow no team owns (the
seed's, which every team runs), and someone outside the builder and admin roles taking a team's workflow live."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import DefinitionStore
from ops_engine.store import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import Ed25519Signer, mint
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from tests.engine.test_lifecycle import definition

PLATFORM = Ed25519Signer.generate("platform-test")
TENANT = "acme"


def person(sub: str, team: str, role: str, *, policies: dict[str, Any] | None = None) -> dict[str, str]:
    claims: dict[str, Any] = {
        "sub": sub,
        "email": f"{sub}@northfield.example",
        "name": sub,
        "kind": "person",
        "aud": ["agents"],
        "tenant_id": TENANT,
        "team_ids": [team],
        "roles": {team: role},
        **({"policies": policies} if policies is not None else {}),
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": team}


BUILDER = person("james", "team_ops", "builder")
ADMIN = person("priya", "team_ops", "admin")
VIEWER = person("vera", "team_ops", "viewer")


async def jwks() -> dict[str, Any]:
    return {"keys": [PLATFORM.public_jwk()]}


async def introspect(_key: str) -> dict[str, Any] | None:
    return None


@pytest.fixture
async def stack() -> AsyncIterator[tuple[AsyncClient, AsyncEngine]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
    auth = Auth(
        Identity(audience="agents", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="agents", verifiers=service_verifiers(settings, "agents")),
    )
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        auth=auth,
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c, engine


async def unowned_live(engine: AsyncEngine, wid: str, *, by: str) -> None:
    """A workflow stored with no team, as the dev seed stores its workflows, and live."""
    store = DefinitionStore(EngineTransactions(engine))
    d = definition(wid)
    with tenant_scope(TENANT):
        version, _ = await store.publish(wid, name="Seeded", definition=d, digest=wid.ljust(64, "s"), now="n", by=by)
        await store.go_live(wid, version)


async def test_a_workflow_no_team_owns_is_paused_by_whoever_the_grid_lets_edit(
    stack: tuple[AsyncClient, AsyncEngine],
) -> None:
    # The roles grid decides in the acting team, as for a team's own workflow: builders and admins edit, viewers do not.
    c, engine = stack
    await unowned_live(engine, "seeded_refunds", by="seed")
    refused = await c.post("/v1/workflows/definitions/seeded_refunds/pause", headers=VIEWER)
    assert refused.status_code == 403, refused.text
    assert (await c.post("/v1/workflows/definitions/seeded_refunds/pause", headers=BUILDER)).status_code == 200


async def test_a_team_workflow_is_published_by_its_builders_and_admins_only(
    stack: tuple[AsyncClient, AsyncEngine],
) -> None:
    c, _ = stack
    saved = await c.post("/v1/workflows/definitions", json={"definition": definition("ops_refunds")}, headers=BUILDER)
    assert saved.status_code == 201, saved.text
    refused = await c.post("/v1/workflows/definitions/ops_refunds/publish-requests", json={}, headers=VIEWER)
    assert refused.status_code == 403, refused.text
    asked = await c.post("/v1/workflows/definitions/ops_refunds/publish-requests", json={}, headers=BUILDER)
    assert asked.status_code == 201, asked.text
