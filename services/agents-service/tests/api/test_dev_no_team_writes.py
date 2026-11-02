"""A dev session acts across every team of its tenant (ops_store.isolation, DEV), so a record it saved under the acting
team alone would be no team's and every team would see it (c-602). A new workflow and a new agent are saved in the team
the session names, or its own; a session with neither is refused with 400 team_required and nothing is saved."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_engine.store import metadata as engine_metadata
from ops_engine.store.tables import engine_definitions
from ops_identity import Auth
from ops_service_kit.settings import Settings

from ..conftest import SEED, FakeGraphModels, scripted_model

DEFINITION: dict[str, Any] = {
    "schemaVersion": 2,
    "id": "wf_dev_owned",
    "name": "Dev owned",
    "nodes": [
        {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
        {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
    ],
    "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
}


@asynccontextmanager
async def _client(team: str) -> AsyncGenerator[tuple[AsyncClient, AsyncEngine]]:
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    auth = Auth.for_dev(settings, audience="agents", name="Dev", email="dev@bank.test", team_id=team)
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        auth=auth,
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client, engine


async def _teams(engine: AsyncEngine) -> dict[str, str | None]:
    """Each stored workflow's and agent's owning team, read past the routes."""
    async with engine.connect() as c:
        d = engine_definitions.c
        flows = (await c.execute(sa.select(d.workflow_id, d.team_id).where(d.workflow_id == "wf_dev_owned"))).all()
        agents = (
            await c.execute(sa.text("SELECT slug, team_id FROM registry_agents WHERE slug LIKE 'branch-desk%'"))
        ).all()
    return {str(k): v for k, v in [*flows, *agents]}


async def test_a_dev_session_saves_a_new_workflow_and_agent_in_the_team_it_names() -> None:
    async with _client("team_ops") as (c, engine):
        cards = {"X-Team-Id": "team_cards"}
        saved = await c.post("/v1/workflows/definitions", json={"definition": DEFINITION}, headers=cards)
        assert saved.status_code == 201, saved.text
        made = await c.post("/v1/agents", json={"name": "Branch Desk", "role": "Answers"}, headers=cards)
        assert made.status_code == 201, made.text
        assert await _teams(engine) == {"wf_dev_owned": "team_cards", "branch-desk": "team_cards"}


async def test_a_dev_session_in_no_team_is_refused_and_saves_nothing() -> None:
    async with _client("") as (c, engine):
        saved = await c.post("/v1/workflows/definitions", json={"definition": DEFINITION})
        assert saved.status_code == 400 and saved.json()["error"]["code"] == "team_required", saved.text
        made = await c.post("/v1/agents", json={"name": "Branch Desk", "role": "Answers"})
        assert made.status_code == 400 and made.json()["error"]["code"] == "team_required", made.text
        assert await _teams(engine) == {}
