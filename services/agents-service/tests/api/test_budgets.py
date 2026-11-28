"""A key's budget (E12), by failure mode: a refused key still opens a thread. A thread's budget and spend are held by
models-service: tests/api/test_gateway_budget.py, test_chain_budget_reserve.py and test_chat_budget.py."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.api.usage import Refusal
from ops_agents.store.base import metadata
from ops_engine.store import metadata as engine_metadata
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model

EMAILS: list[dict[str, Any]] = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "seed" / "dispute_emails.json").read_text()
)


async def thread(client: AsyncClient, graph: str, budget: dict[str, Any] | None = None) -> str:
    body: dict[str, Any] = {"graph": graph, "metadata": {}}
    if budget is not None:
        body["budget"] = budget
    res = await client.post("/v1/threads", json=body)
    assert res.status_code == 201, res.text
    return res.json()["data"]["threadId"]


@asynccontextmanager
async def app_client(
    graph_models: FakeGraphModels, settings: Settings, admit: Callable[[str], Refusal | None] | None = None
) -> AsyncGenerator[tuple[AsyncClient, FastAPI]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=graph_models,
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c,
    ):
        if admit is not None:

            class Keys:
                async def admit(self, key_id: str) -> Refusal | None:
                    return admit(key_id)

            app.state.runtime.keys = Keys()
        yield c, app


async def test_a_key_at_its_cap_cannot_open_a_thread() -> None:
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
    async with app_client(FakeGraphModels(), settings, lambda _key: Refusal("Key budget of 5.00 reached.")) as (c, _):
        res = await c.post("/v1/threads", json={"graph": "complex_workflow", "metadata": {}})
        assert res.status_code == 429
        assert res.json()["error"]["code"] == "key_budget_exhausted"
        assert "5.00" in res.json()["error"]["message"]
        assert (await c.get("/v1/threads")).json()["data"]["data"] == []
