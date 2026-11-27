"""A chain's budget shared by asks that run at once, held at the model gateway, by failure mode: every ask in flight
reads the same spent total and passes together, so the chain spends past its cap; a specialist past the cap makes a
closing call of its own. On PostgreSQL, where each ask's call is admitted on its own connection."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from ops_agent_kernel.testing import Answer, Reply, Structured, ToolCall, last_user_text, tool_names
from ops_agents.api.deps import Runtime
from ops_agents.store.tenancy import tenant_scope
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_metering import Budget
from ops_service_kit.http import Json
from ops_service_kit.settings import Settings
from tests.api.test_action_roles import ADMIN, VIEWER, introspect
from tests.api.test_team_default_agent import URL, say, start
from tests.conftest import SEED, FakeGraphModels, empty_engine
from tests.engine.test_lifecycle_rights import TENANT, jwks
from tests.model_gateway import Gateway, through_gateway
from tests.saves import save_agent

ASKS = 5
CLOSING = "Closing answer from what came back."


async def fan_out(messages: list[Json], tools: list[Json]) -> Answer:
    """The asking agent asks the specialist five times in one response; each specialist reads a customer and then
    answers, so one ask is two model calls. A request offered no tool is a closing answer. Each call takes 50 ms, so
    the five asks are in flight together."""
    await asyncio.sleep(0.05)
    offered = tool_names(tools)
    if last_user_text(messages).startswith("<remember>"):
        return Structured({"memories": []})
    if not offered:
        return CLOSING
    if messages and messages[-1].get("role") == "tool":
        return "Here is what I found."
    if "agent__ag_dispute" in offered:
        return Reply(tool_calls=[ToolCall("agent__ag_dispute", {"question": f"Question {i}?"}) for i in range(ASKS)])
    return Reply(tool_calls=[ToolCall("lookup_customer", {"query": "Maria Lopez"})])


@pytest.fixture
async def stack(database_url: str) -> AsyncIterator[Gateway]:
    settings = Settings(database_url=database_url, seed_dir=SEED)
    auth = Auth(
        Identity(audience="agents", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="agents", verifiers=service_verifiers(settings, "agents"), scopes=settings.service_scopes),
    )
    async with (
        empty_engine(database_url) as engine,
        through_gateway(engine, FakeGraphModels(), fan_out, auth=auth) as g,
    ):
        yield g


async def calls_of(rt: Runtime, thread: str) -> int:
    return sum(t.calls for t in (await rt.usage.totals_by_run(thread)).values()) if rt.usage is not None else 0


async def test_five_asks_at_once_spend_no_more_than_the_cap_and_the_asking_agent_closes_once(stack: Gateway) -> None:
    c, rt = stack.client, stack.runtime
    cap = 3
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
        own = await calls_of(rt, thread)
        rows = [t for t in await rt.graph_store.thread_rows("agent_wrapper") if t.meta_object().get("calledBy")]
        specialists = sum([await calls_of(rt, t.id) for t in rows])
        recorded = (await rt.usage.totals(thread)).calls
    # The asking agent's first call and the specialists' calls are held to the cap between them; the one call past
    # it is the asking agent's closing answer, which the gateway admits once (uc-128 step 11). No specialist closes.
    assert (len(asked), own) == (ASKS, 2), (asked, own)
    assert 1 + specialists <= cap, f"{1 + specialists} model calls were admitted at a cap of {cap}: {asked}"
    assert "answered" in asked and "budget_reached" in asked, asked
    reply = (await c.get(f"/v1/chat/threads/{thread}", headers=VIEWER)).json()["data"]["messages"][-1]
    assert reply["role"] == "assistant" and CLOSING in reply["content"], reply
    # The budget card's spend is every admitted call of the chain, the closing answer included.
    assert recorded == own + specialists, (recorded, own, specialists)
    with tenant_scope(TENANT):
        assert await rt.usage.exhausted(thread) is not None, "the next turn must wait on the budget card"
