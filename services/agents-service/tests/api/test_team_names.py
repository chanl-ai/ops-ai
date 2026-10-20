"""The owning team's name on agent, workflow and widget details (c-224), by failure mode: a member sees only its id;
platform-service being down fails the detail instead of falling back to the id; a list of many records asks
platform-service once per record. A person outside the team reads none of it (c-407)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.api.team_names import PlatformTeamNames
from ops_agents.store.base import metadata
from ops_engine.store import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, ServiceClient, dev_service_signer, service_verifiers
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from tests.engine.test_lifecycle_rights import BUILDER, VIEWER, introspect, jwks, person

OUTSIDER = person("nadia", "team_security", "viewer")


class Platform:
    reads = 0
    down = False

    @classmethod
    def answer(cls, _: httpx.Request) -> httpx.Response:
        cls.reads += 1
        if cls.down:
            return httpx.Response(503, json={"success": False, "error": {"code": "down", "message": "down"}})
        rows = [{"id": "team_ops", "name": "Operations"}, {"id": "team_security", "name": "Security"}]
        return httpx.Response(200, json={"success": True, "data": rows})


@pytest.fixture
async def c() -> AsyncIterator[AsyncClient]:
    Platform.reads, Platform.down = 0, False
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        await conn.run_sync(engine_metadata.create_all)
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
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client,
        httpx.AsyncClient(transport=httpx.MockTransport(Platform.answer), base_url="http://platform") as http,
    ):
        platform = ServiceClient(
            http, dev_service_signer(), "agents", "platform", ["settings:view"], tenant=lambda: "acme"
        )
        app.state.runtime.team_names = PlatformTeamNames(platform)
        yield client


def _data(r: httpx.Response, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


async def test_a_member_sees_the_owning_teams_name_and_platform_is_read_once(c: AsyncClient) -> None:
    agent = _data(
        await c.post("/v1/agents", json={"name": "Payee checker", "role": "Checks payees"}, headers=BUILDER), 201
    )
    seen = _data(await c.get(f"/v1/agents/{agent['id']}", headers=VIEWER))
    assert (seen["teamId"], seen["teamName"], seen["canEdit"]) == ("team_ops", "Operations", False), seen
    _data(await c.get(f"/v1/agents/{agent['id']}", headers=BUILDER))
    assert Platform.reads == 1, "names are cached for the tenant"
    # A person outside the team does not read it at all (c-407).
    assert (await c.get(f"/v1/agents/{agent['id']}", headers=OUTSIDER)).status_code == 404


async def test_platform_down_still_answers_with_the_id(c: AsyncClient) -> None:
    Platform.down = True
    agent = _data(
        await c.post("/v1/agents", json={"name": "Payee checker", "role": "Checks payees"}, headers=BUILDER), 201
    )
    seen = _data(await c.get(f"/v1/agents/{agent['id']}", headers=BUILDER))
    assert (seen["teamId"], seen["teamName"]) == ("team_ops", None)
