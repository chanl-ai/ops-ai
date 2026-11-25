"""A budget shared by asks that run at once, by failure mode: every ask in flight reads the same spent total and
passes together, so the chain spends past its cap. On PostgreSQL, where each ask's check runs on its own connection:
the in-memory SQLite fixtures share one connection and cannot run two checks at once."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.store.tenancy import tenant_scope
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_metering import Budget
from ops_service_kit.settings import Settings
from tests.api.test_action_roles import ADMIN, VIEWER, introspect
from tests.api.test_team_default_agent import URL, say, start
from tests.conftest import SEED, FakeGraphModels, empty_engine, fixture_knowledge, structured
from tests.engine.test_lifecycle_rights import TENANT, jwks
from tests.saves import save_agent

ASKS = 5
CLOSING = "Closing answer from what came back."
Stack = tuple[AsyncClient, Runtime]


def _plan(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """The asking agent asks the specialist five times in one response; each specialist reads a customer and then
    answers, so one ask is two model calls. A request offered no tool is the asking agent's closing answer."""
    last = messages[-1]
    tools = {t.name for t in info.function_tools}
    asked = [p.content for p in last.parts if isinstance(p, UserPromptPart)] if isinstance(last, ModelRequest) else []
    if any(isinstance(text, str) and text.startswith("<remember>") for text in asked):
        return structured(info, {"memories": []})
    if not tools:
        return ModelResponse(parts=[TextPart(CLOSING)])
    if isinstance(last, ModelRequest) and any(isinstance(p, ToolReturnPart) for p in last.parts):
        return ModelResponse(parts=[TextPart("Here is what I found.")])
    if "agent__ag_dispute" in tools:
        asks = [ToolCallPart("agent__ag_dispute", {"question": f"Question {i}?"}, f"ask{i}") for i in range(ASKS)]
        return ModelResponse(parts=asks)
    return ModelResponse(parts=[ToolCallPart("lookup_customer", {"query": "Maria Lopez"}, "read0")])


def fan_out_model() -> FunctionModel:
    """Each model call takes 50 ms, so the five asks are in flight together."""

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        await asyncio.sleep(0.05)
        return _plan(messages, info)

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        await asyncio.sleep(0.05)
        for i, part in enumerate(_plan(messages, info).parts):
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                called = DeltaToolCall(
                    name=part.tool_name, json_args=json.dumps(part.args), tool_call_id=part.tool_call_id
                )
                yield {i: called}

    return FunctionModel(respond, stream_function=stream)


@pytest.fixture
async def stack(database_url: str) -> AsyncIterator[Stack]:
    settings = Settings(database_url=database_url, seed_dir=SEED)
    auth = Auth(
        Identity(audience="agents", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="agents", verifiers=service_verifiers(settings, "agents"), scopes=settings.service_scopes),
    )
    async with empty_engine(database_url) as engine:
        app = create_app(
            settings,
            model=fan_out_model(),
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
            yield c, cast(Runtime, app.state.runtime)


async def test_five_asks_at_once_spend_no_more_than_the_cap_and_the_asking_agent_closes_once(stack: Stack) -> None:
    c, rt = stack
    cap = 8
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    # Room for five tool calls a reply, so the budget is the only thing that stops an ask.
    saved = await save_agent(c, "ag_branch", {"guardrails": {"maxToolCallsPerTurn": 10}}, headers=ADMIN)
    assert saved.status_code == 200, saved.text
    body = {"version": saved.json()["data"]["version"], "note": "go"}
    live = await c.post("/v1/agents/ag_branch/publish-requests", json=body, headers=ADMIN)
    assert live.status_code == 201 and live.json()["data"]["status"] == "approved", live.text
    thread = (await start(c, VIEWER))["id"]
    assert rt.usage is not None and rt.graph_store is not None
    with tenant_scope(TENANT):
        await rt.usage.set_budget(thread, Budget(max_calls=cap))
    events = await say(c, thread, "Ask all five.", VIEWER)
    outputs = [e["call"]["output"] for e in events if e.get("type") == "tool_end"]
    asked = [o.get("status") for o in outputs]
    # Every ask ran as an ask: none failed for a reason of its own, which would make the count below a smaller one.
    assert set(asked) <= {"answered", "budget_reached"}, outputs
    with tenant_scope(TENANT):
        own = sum(r.calls for r in await rt.usage.calls.calls(thread))
        rows = [t for t in await rt.graph_store.thread_rows("agent_wrapper") if t.meta_object().get("calledBy")]
        specialists = sum([r.calls for t in rows for r in await rt.usage.calls.calls(t.id)])
        recorded = (await rt.usage.totals(thread)).calls
    # The asking agent's first call and the specialists' calls are held to the cap between them; the one call past
    # it is the asking agent's closing answer, which no budget check refuses (uc-128 step 11).
    assert (len(asked), own) == (ASKS, 2), (asked, own)
    assert 1 + specialists <= cap, f"{1 + specialists} model calls were admitted at a cap of {cap}: {asked}"
    assert "answered" in asked and "budget_reached" in asked, asked
    reply = (await c.get(f"/v1/chat/threads/{thread}", headers=VIEWER)).json()["data"]["messages"][-1]
    assert reply["role"] == "assistant" and CLOSING in reply["content"], reply
    # Nothing stays reserved once every call has returned: the spend a person is shown is the calls recorded.
    assert recorded == own + specialists, (recorded, own, specialists)
    with tenant_scope(TENANT):
        assert await rt.usage.exhausted(thread) is not None, "the next turn must wait on the budget card"
