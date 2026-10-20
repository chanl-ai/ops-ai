"""Thread budgets and usage (E12), by failure mode: a thread runs past its cap, a paused thread does not say why, a
rejected pause keeps running, a refused key still opens a thread, a scripted model is charged or a priced one is not,
and a crashed attempt's usage goes uncounted."""

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
from ops_agents.api.sweeper import recover
from ops_agents.api.usage import Refusal
from ops_agents.graphs.models import Facts
from ops_agents.store.graphs import metadata
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model, sse_events

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


async def run(client: AsyncClient, tid: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    res = await client.post(f"/v1/threads/{tid}/runs/stream", json=body)
    assert res.status_code == 200, res.text
    return sse_events(res.text)


async def state(client: AsyncClient, tid: str) -> dict[str, Any]:
    return (await client.get(f"/v1/threads/{tid}/state")).json()["data"]


async def calls_without_budget(client: AsyncClient) -> int:
    tid = await thread(client, "complex_workflow")
    await run(client, tid, {"input": {"email": EMAILS[1]}})
    return (await state(client, tid))["cost"]["calls"]


async def test_thread_pauses_mid_loop_at_its_cap_says_why_and_continues_when_raised(
    client: AsyncClient, graph_models: FakeGraphModels
) -> None:
    graph_models.scores = [0.1]  # three drafts and three grades: the cap lands inside the redraft loop
    full = await calls_without_budget(client)
    graph_models.graded = 0
    cap = full - 2
    tid = await thread(client, "complex_workflow", {"maxCalls": cap})
    events = await run(client, tid, {"input": {"email": EMAILS[1]}})
    assert events[-1]["data"]["status"] == "interrupted"
    s = await state(client, tid)
    assert s["interrupt"]["payload"]["kind"] == "budget_exhausted"
    assert s["interrupt"]["payload"]["limit"] == "calls" and s["interrupt"]["payload"]["cap"] == str(cap)
    assert s["cost"]["calls"] == cap and s["budget"]["maxCalls"] == cap
    assert s["next"] and s["next"][0] in {"draft", "grade"}

    await run(client, tid, {"resume": {"decision": "approved", "budget": {"maxCalls": full}}})
    s = await state(client, tid)
    assert s["interrupt"]["payload"]["kind"] == "review"
    assert s["cost"]["calls"] == full and s["budget"]["maxCalls"] == full


async def test_rejecting_a_budget_pause_stops_the_case(client: AsyncClient) -> None:
    tid = await thread(client, "complex_workflow", {"maxCalls": 1})
    await run(client, tid, {"input": {"email": EMAILS[1]}})
    events = await run(client, tid, {"resume": {"decision": "rejected"}})
    assert events[-1]["event"] == "error" or events[-1]["data"]["status"] == "error", events[-3:]
    assert (await state(client, tid))["cost"]["calls"] == 1


@asynccontextmanager
async def app_client(
    graph_models: FakeGraphModels, settings: Settings, admit: Callable[[str], Refusal | None] | None = None
) -> AsyncGenerator[tuple[AsyncClient, FastAPI]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
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
        assert (await c.get("/v1/threads")).json()["data"] == []


async def agent_turn_cost(prices: dict[str, dict[str, str]]) -> dict[str, Any]:
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, prices=prices)
    async with app_client(FakeGraphModels(), settings) as (c, _):
        tid = await thread(c, "agent_wrapper")
        await run(c, tid, {"input": {"agent_id": "ag_branch", "message": "When does the Elm Street branch open?"}})
        return (await state(c, tid))["cost"]


async def test_scripted_model_costs_nothing_and_a_priced_alias_does() -> None:
    free = await agent_turn_cost({})
    assert free["inputTokens"] > 0 and free["cost"] == "0.000000"
    priced = await agent_turn_cost({"default": {"input": "1.25", "output": "10"}})
    assert priced["inputTokens"] == free["inputTokens"]
    expected = (priced["inputTokens"] * 1.25 + priced["outputTokens"] * 10) / 1_000_000
    assert abs(float(priced["cost"]) - expected) < 0.000002 and float(priced["cost"]) > 0


class CrashOnce(FakeGraphModels):
    """Its first extract call fails, as a provider error or a killed process would: the call was made and is paid."""

    def __init__(self) -> None:
        super().__init__()
        self.crashed = False

    async def extract(self, category: str, name: str, text: str) -> Facts:
        if not self.crashed:
            self.crashed = True
            raise RuntimeError("provider connection reset")
        return await super().extract(category, name, text)


async def test_a_crashed_attempt_and_its_rerun_are_both_counted() -> None:
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
    async with app_client(FakeGraphModels(), settings) as (c, _):
        full = await calls_without_budget(c)
    models = CrashOnce()
    async with app_client(models, settings) as (c, app):
        tid = await thread(c, "complex_workflow")
        await run(c, tid, {"input": {"email": EMAILS[1]}})
        assert models.crashed
        failed = (await c.get(f"/v1/threads/{tid}/runs")).json()["data"][0]["runId"]
        # The sweeper's recovery: continue from the last checkpoint; only the failed extract runs again.
        assert await recover(app.state.runtime, tid, failed)
        s = await state(c, tid)
        assert s["interrupt"]["payload"]["kind"] == "review"
        assert s["cost"]["calls"] == full + 1
        runs = (await c.get(f"/v1/threads/{tid}/runs")).json()["data"]
        assert sum(r["cost"]["calls"] for r in runs if r["cost"]) == full + 1
