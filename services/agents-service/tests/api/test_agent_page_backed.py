"""The agent page shows what works (c-068 T002 to T004), by failure mode: the test panel promising a different
approval from the one a real run opens; recent runs missing a chat or listing another agent's; and a control the
page offers that the runtime never reads."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.agent_registry import CONTROLS, GUARDRAILS, definition_of
from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.store.base import metadata
from ops_service_kit.settings import Settings
from tests.api.test_chat import new_thread, send
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model

WIRE = "Place a 24-hour hold on wire W-88213"


@pytest.fixture
async def stack() -> AsyncIterator[tuple[AsyncClient, Runtime]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(
        Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED),
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
        yield client, cast(Runtime, app.state.runtime)


async def test_the_test_panel_shows_the_approval_a_real_run_opens(stack: tuple[AsyncClient, Runtime]) -> None:
    client, _ = stack
    turn = (await client.post("/v1/agents/ag_fraud/test", json={"message": WIRE})).json()["data"]
    thread = await new_thread(client)
    _, events = await send(client, thread["id"], {"content": WIRE})
    widget = next(e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval")
    real = widget.get("data", widget)
    shown = turn["wouldPause"]
    assert (shown["tool"], shown["action"], shown["stepUp"]) == (real["tool"], real["action"], real["stepUp"]), (
        shown,
        widget,
    )


async def test_recent_runs_are_the_agents_own_threads_newest_first(stack: tuple[AsyncClient, Runtime]) -> None:
    client, _ = stack
    first = await new_thread(client)
    await send(client, first["id"], {"content": "What is the daily wire limit?"})
    other = await new_thread(client, "ag_branch", ["kb_support"])
    second = await new_thread(client)
    runs = (await client.get("/v1/agents/ag_fraud/runs")).json()["data"]
    assert [r["threadId"] for r in runs] == [second["id"], first["id"]], runs
    assert {r["kind"] for r in runs} == {"chat"} and other["id"] not in [r["threadId"] for r in runs]
    assert (await client.get("/v1/agents/ag_nobody/runs")).status_code == 404


def test_the_page_offers_exactly_the_guardrail_settings_a_turn_reads() -> None:
    spec: dict[str, Any] = {"name": "A", "role": "B", "instructions": "C", "guardrails": dict(GUARDRAILS)}
    base = definition_of("ag_x", 1, spec)
    changed = {
        "redactPii": False,
        "maxToolCallsPerTurn": 2,
        "maxModelCallsPerTurn": 3,
        "maxModelCallsPerConversation": 7,
        "maxCostPerConversation": 9.5,
        "whenUnsure": "decline",
        "blockedTopics": ["crypto"],
    }
    read = [
        k for k, v in changed.items() if definition_of("ag_x", 1, spec | {"guardrails": {**GUARDRAILS, k: v}}) != base
    ]
    assert read == CONTROLS["guardrails"], f"the page offers {CONTROLS['guardrails']}; a turn reads {read}"


async def test_the_agent_says_which_controls_work(stack: tuple[AsyncClient, Runtime]) -> None:
    client, _ = stack
    fraud = (await client.get("/v1/agents/ag_fraud")).json()["data"]
    assert fraud["controls"] == {
        "channels": ["chat"],
        "guardrails": [
            "redactPii",
            "maxToolCallsPerTurn",
            "maxModelCallsPerTurn",
            "maxModelCallsPerConversation",
            "maxCostPerConversation",
        ],
        "evals": False,
    }


async def test_caps_are_optional_numbers_with_no_ceiling(stack: tuple[AsyncClient, Runtime]) -> None:
    """Caps are optional or realistically large; empty is no cap. Seeds keep theirs low."""
    client, rt = stack
    made = (await client.post("/v1/agents", json={"name": "Big Job", "role": "Works long"})).json()["data"]
    assert (made["guardrails"]["maxToolCallsPerTurn"], made["guardrails"]["maxModelCallsPerTurn"]) == (None, 50)
    fraud = (await client.get("/v1/agents/ag_fraud")).json()["data"]
    assert fraud["guardrails"]["maxToolCallsPerTurn"] == 6 and fraud["guardrails"]["maxModelCallsPerTurn"] == 8
    caps = {**fraud["guardrails"], "maxToolCallsPerTurn": 250, "maxModelCallsPerTurn": None}
    saved = await client.patch("/v1/agents/ag_fraud", json={"guardrails": caps})
    assert saved.status_code == 200, saved.text
    spec = (await client.get("/v1/agents/ag_fraud")).json()["data"]
    defn = definition_of("ag_fraud", spec["version"], {"name": "x", "role": "y", "guardrails": spec["guardrails"]})
    assert (defn.max_tool_calls, defn.max_model_calls) == (250, 50), "an empty model-call cap is the platform's 50"
    settings = rt.catalog.settings_for(defn, "m")
    assert (settings.max_tool_calls, settings.max_steps) == (250, 50)
    zero = await client.patch("/v1/agents/ag_fraud", json={"guardrails": {**caps, "maxModelCallsPerTurn": 0}})
    assert zero.status_code == 400, zero.text


def test_a_version_saved_before_the_model_call_cap_keeps_eight() -> None:
    old = {"name": "x", "role": "y", "guardrails": {"maxToolCallsPerTurn": 6, "redactPii": True}}
    assert definition_of("ag_x", 1, old).max_model_calls == 8


def test_no_saved_model_call_cap_reaches_the_kernel_as_unlimited() -> None:
    """None would become pydantic-ai's request_limit=None: a looping agent spending real calls until the deadline."""
    for caps in ({"maxModelCallsPerTurn": None}, {}, {"maxModelCallsPerTurn": 400}):
        defn = definition_of("ag_x", 1, {"name": "x", "role": "y", "guardrails": caps})
        assert isinstance(defn.max_model_calls, int) and defn.max_model_calls > 0, (caps, defn.max_model_calls)
