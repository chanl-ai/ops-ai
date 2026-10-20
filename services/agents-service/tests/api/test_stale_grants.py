"""Grants whose operation the tool directory no longer offers (c-048 T010, G22), by failure mode: a stale grant
hidden from the agent's owner, a stale grant blocking every later save, a stale-grant drop that also lets an unknown
new grant through, and an agent page failing because tools-service cannot answer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.activities.tool_directory import CatalogTools, OperationRef, ToolsUnavailable
from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model


@dataclass
class Directory:
    """The fixture catalogue minus `withdrawn`; `down` makes it answer as tools-service unreachable."""

    inner: CatalogTools
    withdrawn: set[str]
    down: bool = False

    async def operations(self) -> list[OperationRef]:
        if self.down:
            raise ToolsUnavailable("The tools service cannot be reached.")
        return [o for o in await self.inner.operations() if o.name not in self.withdrawn]


@pytest.fixture
async def setup() -> AsyncIterator[tuple[AsyncClient, Directory]]:
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        rt = app.state.runtime
        directory = Directory(CatalogTools(rt.catalog), withdrawn={"lookup_account"})
        rt.tool_directory = directory
        yield client, directory


async def test_a_grant_no_longer_offered_is_listed_stale(setup: tuple[AsyncClient, Directory]) -> None:
    client, _ = setup
    agent = (await client.get("/v1/agents/ag_fraud")).json()["data"]
    assert agent["toolIds"] == ["lookup_account", "place_wire_hold"], "the grant is kept until the next save"
    assert agent["staleToolIds"] == ["lookup_account"]
    listed = (await client.get("/v1/agents", params={"search": "Wire Fraud"})).json()["data"]["data"]
    assert listed[0]["staleToolIds"] == ["lookup_account"]


async def test_saving_drops_the_stale_grant_and_keeps_the_rest(setup: tuple[AsyncClient, Directory]) -> None:
    client, _ = setup
    r = await client.patch(
        "/v1/agents/ag_fraud", json={"toolIds": ["lookup_account", "place_wire_hold", "request_document"]}
    )
    assert r.status_code == 200, r.text
    saved = r.json()["data"]
    assert saved["toolIds"] == ["place_wire_hold", "request_document"]
    assert saved["staleToolIds"] == []


async def test_a_new_grant_the_directory_does_not_offer_is_still_refused(setup: tuple[AsyncClient, Directory]) -> None:
    client, _ = setup
    r = await client.patch("/v1/agents/ag_branch", json={"toolIds": ["lookup_customer", "lookup_account"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unknown_tool", r.text


async def test_the_agent_page_answers_when_tools_service_cannot(setup: tuple[AsyncClient, Directory]) -> None:
    client, directory = setup
    directory.down = True
    r = await client.get("/v1/agents/ag_fraud")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["staleToolIds"] == []
